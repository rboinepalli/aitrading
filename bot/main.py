"""
main.py — Entry point for the AI trading bot (v3).

v3 runs THREE strategies simultaneously in each loop tick:
  Strategy A (aggressive_3x)     → TQQQ / SQQQ, TP +18%, SL -9%
  Strategy B (momentum_stocks)   → NVDA/AAPL/MSFT/AMD/TSLA/META/COIN, TP +8%, SL -4%
  Strategy C (aggressive_semis)  → SOXL / SOXS, TP +20%, SL -12%

v3 improvements over v2:
  - Dead zone no longer skips exit checks — positions are monitored all day
  - Trailing stop after partial exit (instead of fixed breakeven)
  - Conviction-scaled position sizing (5/8=80%, 6/8=100%, 7+/8=130%)
  - Dead zone narrowed: 11:30am–1:30pm (was 11am–2pm)
  - SPY open momentum filter: skips entries if SPY contradicts regime in first 30 min
  - Polling at 2-minute intervals (was 5 min) for faster signal detection

Each strategy:
  - Has its own configurable budget (Railway env vars)
  - Has its own daily loss limiter
  - Has its own open position (tracked separately in Supabase)
  - Uses the same conviction scoring engine (5/8 or 6/8 depending on time window)
  - Strategy C always requires 6/8 regardless of window

Loop structure (every 2 min, Mon–Fri 9:30am–3:45pm ET):
  1. Detect market regime (once, shared by all strategies)
  2. Determine time window (PRIMARY / DEAD_ZONE / POWER_HOUR / CLOSED)
  3. Check SPY open momentum filter (first 30 min only)
  4. For each strategy:
     a. Check regime filter
     b. Check daily loss limit
     c. Check open position → exit if needed (partial or full)
     d. Update trailing stop if holding post-partial
     e. If no position and entries allowed → score tickers → enter if score qualifies
"""

import logging
import sys
from datetime import date, datetime, timezone

import pytz
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from broker.alpaca_client import AlpacaClient
from config import load_config, StrategyConfig
from data.market_data import MarketDataClient
from db.supabase_client import SupabaseDB
from exits.exit_manager import check_exit, ExitReason
from risk.daily_limiter import DailyLimiter
from risk.position_manager import calculate_shares
from signals.entry import get_time_window, TimeWindow
from signals.regime import detect_regime, Regime
from strategies.strategy_a import evaluate_strategy_a
from strategies.strategy_b import evaluate_strategy_b
from strategies.strategy_c import evaluate_strategy_c

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
_data = None   # MarketDataClient — Alpaca IEX data

# Per-strategy daily limiters
_limiter_a = None
_limiter_b = None
_limiter_c = None

# Track open trade IDs per strategy (maps strategy_name → trade_id or None)
_open_trade_ids: dict[str, str | None] = {
    "aggressive_3x": None,
    "momentum_stocks": None,
    "aggressive_semis": None,
}


# ---------------------------------------------------------------------------
# SPY open momentum filter
# ---------------------------------------------------------------------------

def _spy_momentum_ok(regime: Regime, window: TimeWindow) -> bool:
    """
    In the first 30 minutes after open (9:30–10:00am ET), verify that SPY
    is moving in the direction of our regime before allowing any entries.

    Why this matters:
      The first 30 min after market open has high noise. Algos, retail, and
      institutional orders all hit at once. A BULL regime detected from the
      200-DMA (a slow daily indicator) can conflict with a bearish open.
      Entering long TQQQ/SOXL when SPY is dropping from the open is a
      common source of early-morning false signals.

    Returns True (allow entries) if:
      - We're not in the first 30 min
      - SPY data is unavailable (fail-open — don't block on data errors)
      - SPY direction matches the regime
    Returns False (skip entries this tick) if regime/SPY direction conflict.
    """
    # Only filter during PRIMARY window in the first 30 min
    if window != TimeWindow.PRIMARY:
        return True

    now_et = datetime.now(ET)
    cutoff = now_et.replace(hour=10, minute=0, second=0, microsecond=0)
    if now_et >= cutoff:
        return True  # past the volatile open window

    try:
        spy_bars = _data.get_intraday_bars("SPY", days=1)
        if spy_bars is None or spy_bars.empty:
            return True

        # Compare latest bar close vs the very first bar open today
        first_open = spy_bars.iloc[0]["Open"]
        latest_close = spy_bars.iloc[-1]["Close"]
        spy_change = (latest_close - first_open) / first_open

        if regime == Regime.BULL and spy_change < -0.002:
            logger.info(
                "SPY filter: BULL regime but SPY down %.2f%% from open — skipping entries this tick",
                spy_change * 100,
            )
            return False

        if regime == Regime.BEAR and spy_change > 0.002:
            logger.info(
                "SPY filter: BEAR regime but SPY up %.2f%% from open — skipping entries this tick",
                spy_change * 100,
            )
            return False

        return True

    except Exception as e:
        logger.warning("SPY momentum filter error: %s — allowing entries", e)
        return True


# ---------------------------------------------------------------------------
# Per-strategy loop logic
# ---------------------------------------------------------------------------

def _run_strategy(
    strategy: StrategyConfig,
    regime: Regime,
    vixy_price: float,
    window: TimeWindow,
    min_score: int,
    limiter: DailyLimiter,
    spy_ok: bool,
) -> None:
    """
    Run one iteration of a single strategy:
    check exits on open position, then evaluate new entries.

    The dead zone (11:30am–1:30pm) still runs this function — it just
    skips entries. Exit checks always run so positions are protected.
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

    # --- Per-strategy min score (strategy can require stricter threshold than global) ---
    if window == TimeWindow.PRIMARY:
        effective_min = max(min_score, strategy.primary_min_score)
    elif window == TimeWindow.POWER_HOUR:
        effective_min = max(min_score, strategy.power_hour_min_score)
    else:
        effective_min = min_score

    # --- Check open position ---
    trade_id = _open_trade_ids.get(strategy_name)

    # Find open position for any ticker this strategy can trade
    active_position = None
    for ticker in strategy.tickers:
        pos = _alpaca.get_open_position(ticker)
        if pos:
            active_position = pos
            break

    # Reconcile: if we think a position is open but Alpaca shows nothing,
    # the position was closed outside the bot (manual close, margin call, etc.)
    if not active_position and trade_id:
        stale_row = _db.get_open_trade_by_id(trade_id)
        if stale_row:
            logger.warning("[%s] Position closed outside bot — reconciling Supabase record", strategy_name)
            _db.close_trade(
                trade_id=trade_id,
                exit_price=0.0,
                exit_time=datetime.now(timezone.utc),
                exit_reason="MANUAL_CLOSE",
                pnl=0.0,
            )
        _open_trade_ids[strategy_name] = None

    if active_position:
        trade_row = _db.get_open_trade(active_position.ticker, strategy_name)
        partial_triggered = trade_row["partial_exit_triggered"] if trade_row else False
        stop_price = trade_row["stop_price"] if trade_row else active_position.entry_price

        # Recover trade_id from Supabase after a bot restart (global resets to None)
        if trade_id is None and trade_row:
            trade_id = trade_row["id"]
            _open_trade_ids[strategy_name] = trade_id
            logger.info("[%s] Recovered trade_id=%s from Supabase after restart", strategy_name, trade_id)

        # Close positions held overnight at the first market-hours tick after a new day.
        if trade_row:
            from datetime import time as _time
            entry_dt = datetime.fromisoformat(
                trade_row["entry_time"].replace("Z", "+00:00")
            ).astimezone(ET)
            market_open = _time(9, 30)
            if entry_dt.date() < date.today() and datetime.now(ET).time() >= market_open:
                logger.info(
                    "[%s] Overnight position %s (entered %s) — closing at market open",
                    strategy_name, active_position.ticker, entry_dt.date(),
                )
                _alpaca.sell_all(active_position.ticker)
                if trade_id:
                    _db.close_trade(
                        trade_id=trade_id,
                        exit_price=active_position.current_price,
                        exit_time=datetime.now(timezone.utc),
                        exit_reason="OVERNIGHT_CLOSE",
                        pnl=active_position.unrealized_pnl,
                    )
                    _open_trade_ids[strategy_name] = None
                return

        exit_decision = check_exit(
            position=active_position,
            strategy=strategy,
            partial_already_triggered=partial_triggered,
            stop_price=stop_price,
            force_close_time=_cfg.force_close_time,
        )

        if exit_decision.should_exit:
            if exit_decision.exit_all:
                logger.info(
                    "[%s] EXIT %s | reason=%s | %s",
                    strategy_name, active_position.ticker,
                    exit_decision.reason.value, exit_decision.detail,
                )
                _alpaca.sell_all(active_position.ticker)
                if trade_id:
                    _db.close_trade(
                        trade_id=trade_id,
                        exit_price=active_position.current_price,
                        exit_time=datetime.now(timezone.utc),
                        exit_reason=exit_decision.reason.value,
                        pnl=active_position.unrealized_pnl,
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
                from alpaca.trading.requests import MarketOrderRequest
                from alpaca.trading.enums import OrderSide, TimeInForce
                req = MarketOrderRequest(
                    symbol=active_position.ticker,
                    qty=half_shares,
                    side=OrderSide.SELL,
                    time_in_force=TimeInForce.DAY,
                )
                _alpaca._client.submit_order(req)
                if trade_id:
                    # Set initial trailing stop: strategy.trailing_stop_pct below current price
                    # This is higher than breakeven — lets profits run instead of locking at entry
                    initial_trail = active_position.current_price * (1 - strategy.trailing_stop_pct)
                    _db.mark_partial_exit(trade_id, stop_price=initial_trail)
        else:
            logger.info("[%s] Holding %s | %s", strategy_name, active_position.ticker, exit_decision.detail)

            # Ratchet trailing stop upward as price moves in our favour (post-partial only)
            if partial_triggered and trade_id and strategy.trailing_stop_pct > 0:
                new_trail = active_position.current_price * (1 - strategy.trailing_stop_pct)
                if new_trail > stop_price:
                    _db.update_stop_price(trade_id, new_trail)

        return  # don't look for new entries while position is open

    # --- No open position — evaluate entry ---
    if window in (TimeWindow.DEAD_ZONE, TimeWindow.CLOSED):
        logger.info("[%s] No entry — time window=%s", strategy_name, window.value)
        return

    # SPY momentum filter — skip entries if early-morning SPY contradicts regime
    if not spy_ok:
        logger.info("[%s] No entry — SPY momentum filter blocked this tick", strategy_name)
        return

    # Score tickers for this strategy
    conviction = None
    if strategy_name == "aggressive_3x":
        conviction = evaluate_strategy_a(regime, vixy_price, effective_min, _cfg, _data)
    elif strategy_name == "aggressive_semis":
        conviction = evaluate_strategy_c(regime, vixy_price, effective_min, _cfg, _data)
    else:
        conviction = evaluate_strategy_b(regime, effective_min, _cfg, _data)

    # Log signal to Supabase regardless of outcome (for audit)
    if conviction:
        _db.insert_signal(
            strategy=strategy_name,
            ticker=conviction.ticker,
            regime=regime.value,
            rsi=conviction.rsi,
            ema_fast=0.0,
            ema_slow=0.0,
            macd=conviction.macd_line,
            vwap=conviction.vwap,
            volume_ratio=conviction.volume_ratio,
            vix=vixy_price,
            conviction_score=conviction.score,
            signal="BUY",
        )

        # Execute the trade — size scaled by conviction score
        buying_power = _alpaca.get_buying_power()
        shares = calculate_shares(
            price=conviction.price,
            buying_power=buying_power,
            max_per_trade=_cfg.max_per_trade_usd,
            strategy_budget=strategy.budget_usd,
            conviction_score=conviction.score,
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
    """Called every 2 minutes by APScheduler during market hours."""
    now_et = datetime.now(ET)
    window, min_score = get_time_window(_cfg)

    # During dead zone: skip regime detection + entries BUT still run exit checks
    # so open positions are protected. We call _run_strategy with a dummy regime
    # only if there are open positions to manage.
    if window == TimeWindow.DEAD_ZONE:
        any_open = any(tid is not None for tid in _open_trade_ids.values())
        if not any_open:
            logger.info("=== Dead zone tick: %s ET — no open positions, skipping ===", now_et.strftime("%H:%M"))
            return
        logger.info("=== Dead zone tick: %s ET — checking exits on open positions ===", now_et.strftime("%H:%M"))

    logger.info("=== Loop tick: %s ET ===", now_et.strftime("%Y-%m-%d %H:%M"))

    # Detect regime (once per tick, shared by all strategies)
    try:
        regime, vixy_price, spy_price, spy_sma = detect_regime(data_client=_data)
    except RuntimeError as e:
        logger.error("Regime detection failed: %s", e)
        _db.log_event("ERROR", f"Regime detection failed: {e}")
        return

    logger.info(
        "Window=%s min_score=%d | Regime=%s | SPY=%.2f SMA200=%.2f | VIXY=%.2f",
        window.value, min_score, regime.value, spy_price, spy_sma, vixy_price,
    )

    # SPY open momentum filter — computed once, shared by all strategies
    spy_ok = _spy_momentum_ok(regime, window)

    # Run all three strategies
    _run_strategy(_cfg.strategy_a, regime, vixy_price, window, min_score, _limiter_a, spy_ok)
    _run_strategy(_cfg.strategy_b, regime, vixy_price, window, min_score, _limiter_b, spy_ok)
    _run_strategy(_cfg.strategy_c, regime, vixy_price, window, min_score, _limiter_c, spy_ok)


def write_daily_summary() -> None:
    """Write EOD summary to Supabase. Called at 4pm ET."""
    logger.info("Writing daily summary...")
    today = date.today()

    all_trades = _db.get_todays_trades(today)
    a_trades = [t for t in all_trades if t.get("strategy") == "aggressive_3x"]
    b_trades = [t for t in all_trades if t.get("strategy") == "momentum_stocks"]
    c_trades = [t for t in all_trades if t.get("strategy") == "aggressive_semis"]

    def _stats(trades):
        pnls = [t["pnl"] for t in trades if t.get("pnl") is not None]
        return sum(pnls), len(trades), sum(1 for p in pnls if p > 0), sum(1 for p in pnls if p <= 0)

    a_pnl, a_count, a_wins, a_losses = _stats(a_trades)
    b_pnl, b_count, b_wins, b_losses = _stats(b_trades)
    c_pnl, c_count, c_wins, c_losses = _stats(c_trades)

    all_pnls = [t["pnl"] for t in all_trades if t.get("pnl") is not None]
    max_drawdown = min(all_pnls) if all_pnls else 0.0

    try:
        regime, _, _, _ = detect_regime(_data)
        regime_str = regime.value
    except Exception:
        regime_str = "UNKNOWN"

    _db.upsert_daily_summary(
        trading_date=today,
        total_pnl=a_pnl + b_pnl + c_pnl,
        trades_taken=a_count + b_count + c_count,
        winning_trades=a_wins + b_wins + c_wins,
        losing_trades=a_losses + b_losses + c_losses,
        max_drawdown=max_drawdown,
        regime_at_close=regime_str,
        strategy_a_pnl=a_pnl,
        strategy_b_pnl=b_pnl,
        strategy_a_trades=a_count,
        strategy_b_trades=b_count,
    )
    _db.log_event(
        "REGIME_CHANGE",
        f"Daily close | A: ${a_pnl:.2f} | B: ${b_pnl:.2f} | C: ${c_pnl:.2f} | Regime: {regime_str}",
    )


def main() -> None:
    """Startup: load config, connect services, start scheduler."""
    global _cfg, _alpaca, _db, _data, _limiter_a, _limiter_b, _limiter_c

    logger.info("Starting AI Trading Bot v3...")

    _cfg = load_config()
    logger.info("Config loaded ✓")

    _alpaca = AlpacaClient(_cfg)
    logger.info("Alpaca connected ✓ — buying power: $%.2f", _alpaca.get_buying_power())

    _db = SupabaseDB(_cfg)
    logger.info("Supabase connected ✓")

    _data = MarketDataClient(_cfg.alpaca_api_key, _cfg.alpaca_secret_key)
    logger.info("MarketDataClient connected ✓")

    _limiter_a = DailyLimiter("aggressive_3x", _cfg.max_daily_loss_usd, _db)
    _limiter_b = DailyLimiter("momentum_stocks", _cfg.max_daily_loss_usd, _db)
    _limiter_c = DailyLimiter("aggressive_semis", _cfg.max_daily_loss_usd, _db)

    _db.log_event(
        "STARTED",
        "Bot v3 started — A (aggressive_3x TQQQ/SQQQ) | B (momentum_stocks) | C (aggressive_semis SOXL/SOXS)",
    )

    scheduler = BlockingScheduler(timezone=ET)

    # Poll every 2 minutes during all market hours.
    # The time-window logic in get_time_window() gates what each tick can do.
    # 9:30–9:58am
    scheduler.add_job(run_loop, CronTrigger(
        day_of_week="mon-fri", hour="9", minute="30,32,34,36,38,40,42,44,46,48,50,52,54,56,58", timezone=ET
    ), id="loop_open")

    # 10:00am–2:58pm (every 2 min)
    scheduler.add_job(run_loop, CronTrigger(
        day_of_week="mon-fri", hour="10-14", minute="*/2", timezone=ET
    ), id="loop_mid")

    # 3:00pm–3:44pm (every 2 min)
    scheduler.add_job(run_loop, CronTrigger(
        day_of_week="mon-fri", hour="15",
        minute="0,2,4,6,8,10,12,14,16,18,20,22,24,26,28,30,32,34,36,38,40,42,44",
        timezone=ET
    ), id="loop_close")

    # EOD summary at 4pm
    scheduler.add_job(write_daily_summary, CronTrigger(
        day_of_week="mon-fri", hour=16, minute=0, timezone=ET
    ), id="daily_summary")

    # Startup tick: recover any positions left open from a previous session
    logger.info("Running startup tick to recover any open positions...")
    run_loop()

    logger.info("Scheduler started — Mon–Fri 9:30am–3:44pm ET (every 2 min)")
    logger.info("Strategy A: TQQQ/SQQQ | Strategy B: NVDA/AAPL/MSFT/AMD/TSLA/META/COIN | Strategy C: SOXL/SOXS")
    logger.info("Dead zone: 11:30am–1:30pm ET | Budgets: A=$%.0f B=$%.0f C=$%.0f",
                _cfg.strategy_a.budget_usd, _cfg.strategy_b.budget_usd, _cfg.strategy_c.budget_usd)

    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("Bot stopped.")


if __name__ == "__main__":
    main()
