"""
main.py — Entry point for the AI trading bot (v2).

v2 runs TWO strategies simultaneously in each loop tick:
  Strategy A (aggressive_3x)    → TQQQ / SQQQ, TP +15%, SL -10%
  Strategy B (conservative_multi) → QQQ/NVDA/AAPL/MSFT/AMD/SPY, TP +5%, SL -3%

Each strategy:
  - Has its own $10,000 budget
  - Has its own daily loss limiter
  - Has its own open position (tracked separately in Supabase)
  - Uses the same conviction scoring engine (5/8 or 6/8 depending on time window)

Loop structure (every 5 min, Mon–Fri 9:30am–3:45pm ET):
  1. Detect market regime (once, shared by both strategies)
  2. Determine time window (PRIMARY / DEAD_ZONE / POWER_HOUR / CLOSED)
  3. For each strategy:
     a. Check regime filter (Strategy B sits out in BEAR/CHOPPY)
     b. Check daily loss limit
     c. Check open position → exit if needed (partial or full)
     d. If no position and entries allowed → score tickers → enter if score qualifies
"""

import logging
import sys
from datetime import date, datetime, timezone

import pytz
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from broker.alpaca_client import AlpacaClient
from config import load_config, StrategyConfig
from db.supabase_client import SupabaseDB
from exits.exit_manager import check_exit, ExitReason
from risk.daily_limiter import DailyLimiter
from risk.position_manager import calculate_shares
from signals.entry import get_time_window, TimeWindow
from signals.regime import detect_regime, Regime
from strategies.strategy_a import evaluate_strategy_a
from strategies.strategy_b import evaluate_strategy_b

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)
ET = pytz.timezone("America/New_York")

# ---------------------------------------------------------------------------
# Global state — initialised once in main(), reused across loop ticks
# ---------------------------------------------------------------------------
_cfg = None
_alpaca = None
_db = None

# Per-strategy daily limiters
_limiter_a = None
_limiter_b = None

# Track open trade IDs per strategy (maps strategy_name → trade_id or None)
_open_trade_ids: dict[str, str | None] = {
    "aggressive_3x": None,
    "conservative_multi": None,
}


# ---------------------------------------------------------------------------
# Per-strategy loop logic
# ---------------------------------------------------------------------------

def _run_strategy(
    strategy: StrategyConfig,
    regime: Regime,
    vix: float,
    window: TimeWindow,
    min_score: int,
    limiter: DailyLimiter,
) -> None:
    """
    Run one iteration of a single strategy:
    check exits on open position, then evaluate new entries.
    """
    global _open_trade_ids
    strategy_name = strategy.name

    # --- Regime filter ---
    if regime.value not in strategy.regime_filter:
        logger.info("[%s] Sitting out — regime=%s not in filter", strategy_name, regime.value)
        return

    # --- Daily loss gate ---
    if limiter.is_halted():
        logger.warning("[%s] Daily loss limit hit — no new trades today", strategy_name)
        return

    # --- Check open position ---
    trade_id = _open_trade_ids.get(strategy_name)

    # Find open position for any ticker this strategy can trade
    active_position = None
    for ticker in strategy.tickers:
        pos = _alpaca.get_open_position(ticker)
        if pos:
            active_position = pos
            break

    if active_position:
        # Look up stored trade metadata (partial exit state, stop price)
        trade_row = _db.get_open_trade(active_position.ticker, strategy_name)
        partial_triggered = trade_row["partial_exit_triggered"] if trade_row else False
        stop_price = trade_row["stop_price"] if trade_row else active_position.entry_price

        exit_decision = check_exit(
            position=active_position,
            strategy=strategy,
            partial_already_triggered=partial_triggered,
            stop_price=stop_price,
            force_close_time=_cfg.force_close_time,
        )

        if exit_decision.should_exit:
            if exit_decision.exit_all:
                # Full exit — close entire position
                logger.info(
                    "[%s] EXIT %s | reason=%s | %s",
                    strategy_name, active_position.ticker,
                    exit_decision.reason.value, exit_decision.detail,
                )
                _alpaca.sell_all(active_position.ticker)
                if trade_id:
                    pnl = active_position.unrealized_pnl
                    _db.close_trade(
                        trade_id=trade_id,
                        exit_price=active_position.current_price,
                        exit_time=datetime.now(timezone.utc),
                        exit_reason=exit_decision.reason.value,
                        pnl=pnl,
                    )
                    _open_trade_ids[strategy_name] = None
            else:
                # Partial exit — sell 50% of shares
                half_shares = max(1, int(active_position.shares / 2))
                logger.info(
                    "[%s] PARTIAL EXIT %s | selling %d of %d shares | %s",
                    strategy_name, active_position.ticker,
                    half_shares, int(active_position.shares), exit_decision.detail,
                )
                # Alpaca: sell specific quantity by submitting a sell order for half
                from alpaca.trading.requests import MarketOrderRequest
                from alpaca.trading.enums import OrderSide, TimeInForce
                from alpaca.trading.client import TradingClient
                # Use alpaca client directly for partial sell
                req = MarketOrderRequest(
                    symbol=active_position.ticker,
                    qty=half_shares,
                    side=OrderSide.SELL,
                    time_in_force=TimeInForce.DAY,
                )
                _alpaca._client.submit_order(req)
                if trade_id:
                    # Mark partial exit and move stop to breakeven
                    _db.mark_partial_exit(trade_id, stop_price=active_position.entry_price)
        else:
            logger.info("[%s] Holding %s | %s", strategy_name, active_position.ticker, exit_decision.detail)
        return  # don't look for new entries while position is open

    # --- No open position — evaluate entry ---
    if window in (TimeWindow.DEAD_ZONE, TimeWindow.CLOSED):
        logger.info("[%s] No entry — time window=%s", strategy_name, window.value)
        return

    # Score tickers for this strategy
    conviction = None
    if strategy_name == "aggressive_3x":
        conviction = evaluate_strategy_a(regime, vix, min_score, _cfg)
    else:
        conviction = evaluate_strategy_b(regime, min_score, _cfg)

    # Log signal to Supabase regardless of outcome (for audit)
    if conviction:
        snap_ticker = conviction.ticker
        _db.insert_signal(
            strategy=strategy_name,
            ticker=snap_ticker,
            regime=regime.value,
            rsi=conviction.rsi,
            ema_fast=0.0,   # simplified — full snap available in scorer
            ema_slow=0.0,
            macd=conviction.macd_line,
            vwap=conviction.vwap,
            volume_ratio=conviction.volume_ratio,
            vix=vix,
            conviction_score=conviction.score,
            signal="BUY",
        )

        # Execute the trade
        buying_power = _alpaca.get_buying_power()
        shares = calculate_shares(
            price=conviction.price,
            buying_power=buying_power,
            max_per_trade=_cfg.max_per_trade_usd,
            strategy_budget=strategy.budget_usd,
        )

        if shares > 0:
            _alpaca.buy(conviction.ticker, shares)
            trade_id = _db.insert_trade(
                strategy=strategy_name,
                ticker=conviction.ticker,
                entry_price=conviction.price,
                shares=shares,
                entry_time=datetime.now(timezone.utc),
                regime=regime.value,
                conviction_score=conviction.score,
                signals_triggered=conviction.signals_fired,
            )
            _open_trade_ids[strategy_name] = trade_id
        else:
            logger.warning("[%s] BUY signal but 0 shares — insufficient buying power", strategy_name)
    else:
        logger.info("[%s] No qualifying signal this tick", strategy_name)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run_loop() -> None:
    """Called every 5 minutes by APScheduler during market hours."""
    now_et = datetime.now(ET)
    logger.info("=== Loop tick: %s ET ===", now_et.strftime("%Y-%m-%d %H:%M"))

    # 1. Detect regime (once per tick, shared by both strategies)
    try:
        regime, vix, spy_price, spy_sma = detect_regime(
            vix_bear_threshold=_cfg.vix_bear_threshold,
            vix_bull_threshold=_cfg.vix_bull_threshold,
        )
    except RuntimeError as e:
        logger.error("Regime detection failed: %s", e)
        _db.log_event("ERROR", f"Regime detection failed: {e}")
        return

    # 2. Determine time window
    window, min_score = get_time_window(_cfg)
    logger.info("Window=%s min_score=%d | Regime=%s VIX=%.1f", window.value, min_score, regime.value, vix)

    # 3. Run both strategies
    _run_strategy(_cfg.strategy_a, regime, vix, window, min_score, _limiter_a)
    _run_strategy(_cfg.strategy_b, regime, vix, window, min_score, _limiter_b)


def write_daily_summary() -> None:
    """Write EOD summary to Supabase. Called at 4pm ET."""
    logger.info("Writing daily summary...")
    today = date.today()

    all_trades = _db.get_todays_trades(today)
    a_trades = [t for t in all_trades if t.get("strategy") == "aggressive_3x"]
    b_trades = [t for t in all_trades if t.get("strategy") == "conservative_multi"]

    def _stats(trades):
        pnls = [t["pnl"] for t in trades if t.get("pnl") is not None]
        return sum(pnls), len(trades), sum(1 for p in pnls if p > 0), sum(1 for p in pnls if p <= 0)

    a_pnl, a_count, a_wins, a_losses = _stats(a_trades)
    b_pnl, b_count, b_wins, b_losses = _stats(b_trades)

    all_pnls = [t["pnl"] for t in all_trades if t.get("pnl") is not None]
    max_drawdown = min(all_pnls) if all_pnls else 0.0

    try:
        regime, vix, _, _ = detect_regime(_cfg.vix_bear_threshold, _cfg.vix_bull_threshold)
        regime_str = regime.value
    except Exception:
        regime_str = "UNKNOWN"

    _db.upsert_daily_summary(
        trading_date=today,
        total_pnl=a_pnl + b_pnl,
        trades_taken=a_count + b_count,
        winning_trades=a_wins + b_wins,
        losing_trades=a_losses + b_losses,
        max_drawdown=max_drawdown,
        regime_at_close=regime_str,
        strategy_a_pnl=a_pnl,
        strategy_b_pnl=b_pnl,
        strategy_a_trades=a_count,
        strategy_b_trades=b_count,
    )
    _db.log_event("REGIME_CHANGE", f"Daily close | A: ${a_pnl:.2f} | B: ${b_pnl:.2f} | Regime: {regime_str}")


def main() -> None:
    """Startup: load config, connect services, start scheduler."""
    global _cfg, _alpaca, _db, _limiter_a, _limiter_b

    logger.info("Starting AI Trading Bot v2...")

    _cfg = load_config()
    logger.info("Config loaded ✓")

    _alpaca = AlpacaClient(_cfg)
    logger.info("Alpaca connected ✓ — buying power: $%.2f", _alpaca.get_buying_power())

    _db = SupabaseDB(_cfg)
    logger.info("Supabase connected ✓")

    _limiter_a = DailyLimiter("aggressive_3x", _cfg.max_daily_loss_usd, _db)
    _limiter_b = DailyLimiter("conservative_multi", _cfg.max_daily_loss_usd, _db)

    _db.log_event("STARTED", "Bot v2 started — Strategy A (aggressive_3x) + Strategy B (conservative_multi)")

    scheduler = BlockingScheduler(timezone=ET)

    # Primary window: 9:30–10:55am
    scheduler.add_job(run_loop, CronTrigger(
        day_of_week="mon-fri", hour="9", minute="30,35,40,45,50,55", timezone=ET
    ), id="loop_open")

    # Full hours: 10am–2:55pm
    scheduler.add_job(run_loop, CronTrigger(
        day_of_week="mon-fri", hour="10-14", minute="*/5", timezone=ET
    ), id="loop_mid")

    # Close window: 3pm–3:45pm
    scheduler.add_job(run_loop, CronTrigger(
        day_of_week="mon-fri", hour="15", minute="0,5,10,15,20,25,30,35,40,45", timezone=ET
    ), id="loop_close")

    # EOD summary at 4pm
    scheduler.add_job(write_daily_summary, CronTrigger(
        day_of_week="mon-fri", hour=16, minute=0, timezone=ET
    ), id="daily_summary")

    logger.info("Scheduler started — Mon–Fri 9:30am–3:45pm ET")
    logger.info("Strategy A: TQQQ/SQQQ | Strategy B: QQQ/NVDA/AAPL/MSFT/AMD/SPY")

    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("Bot stopped.")


if __name__ == "__main__":
    main()
