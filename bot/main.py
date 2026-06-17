"""
main.py — Entry point for the AI trading bot.

This is the file Railway runs: `python main.py`

What happens here:
  1. Load config and connect to all services (Alpaca, Supabase)
  2. Schedule the main trading loop to run every 5 minutes
  3. Schedule a daily summary job to run at 4pm ET

The loop itself (`run_loop`) is the core of the bot.
Every 5 minutes it:
  - Detects the market regime
  - Checks risk limits
  - Looks for entry signals (if no position open)
  - Checks exit conditions (if position is open)
  - Logs everything to Supabase

APScheduler is a job scheduler for Python — similar to cron but programmatic.
It's like setInterval in JavaScript, but timezone-aware and production-grade.

Python logging:
  Python's built-in `logging` module is the standard way to emit log messages.
  It's similar to console.log but with levels (DEBUG, INFO, WARNING, ERROR)
  and structured configuration. Railway captures stdout/stderr automatically.
"""

import logging
import sys
from datetime import date, datetime, timezone

import pytz
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from broker.alpaca_client import AlpacaClient
from config import load_config
from db.supabase_client import SupabaseDB
from exits.exit_manager import check_exit
from risk.daily_limiter import DailyLimiter
from risk.position_manager import calculate_shares
from signals.entry import Signal, evaluate_entry
from signals.regime import detect_regime, Regime

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
# basicConfig sets up a root logger that all modules inherit from.
# %(asctime)s  → timestamp
# %(name)s     → module name (e.g. "signals.regime")
# %(levelname)s→ INFO / WARNING / ERROR
# %(message)s  → the log message
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    stream=sys.stdout,  # Railway captures stdout
)
logger = logging.getLogger(__name__)

ET = pytz.timezone("America/New_York")


# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------
# We initialise these once at startup and reuse across loop iterations.
# In a larger app you'd use dependency injection, but a module-level variable
# is idiomatic Python for a single-process worker like this.
_cfg = None
_alpaca = None
_db = None
_limiter = None
_current_trade_id: str | None = None  # UUID of the currently open trade in Supabase


def run_loop():
    """
    Main trading loop — called every 5 minutes by APScheduler.

    This is the entire strategy in one function:
      1. Regime detection
      2. Risk check (daily loss limit)
      3. Exit check (if position open)
      4. Entry check (if no position open)
      5. Signal logging
    """
    global _current_trade_id

    now_et = datetime.now(ET)
    logger.info("=== Loop tick: %s ET ===", now_et.strftime("%Y-%m-%d %H:%M"))

    # -----------------------------------------------------------------------
    # Step 1 — Detect regime
    # -----------------------------------------------------------------------
    try:
        regime, vix, spy_price, spy_sma = detect_regime(
            vix_bear_threshold=_cfg.vix_bear_threshold,
            vix_bull_threshold=_cfg.vix_bull_threshold,
        )
    except RuntimeError as e:
        logger.error("Regime detection failed: %s — skipping loop", e)
        return

    # -----------------------------------------------------------------------
    # Step 2 — Daily loss circuit breaker
    # -----------------------------------------------------------------------
    if _limiter.is_halted():
        logger.warning("Trading halted for today (daily loss limit reached)")
        return

    # -----------------------------------------------------------------------
    # Step 3 — Check if we have an open position and need to exit
    # -----------------------------------------------------------------------
    # Choose which ticker we might be holding based on regime.
    # In v1, we only ever hold the ticker that matches the entry regime.
    # We check both bull and bear tickers in case regime flipped mid-day.
    active_position = None
    for ticker in [_cfg.bull_ticker, _cfg.bear_ticker]:
        pos = _alpaca.get_open_position(ticker)
        if pos:
            active_position = pos
            break

    if active_position:
        exit_decision = check_exit(active_position, _cfg)

        if exit_decision.should_exit:
            logger.info(
                "Exiting %s | reason=%s | %s",
                active_position.ticker, exit_decision.reason.value, exit_decision.detail,
            )
            _alpaca.sell_all(active_position.ticker)

            # Update the trade record in Supabase
            if _current_trade_id:
                pnl = active_position.unrealized_pnl  # at the moment of decision
                _db.close_trade(
                    trade_id=_current_trade_id,
                    exit_price=active_position.current_price,
                    exit_time=datetime.now(timezone.utc),
                    exit_reason=exit_decision.reason.value,
                    pnl=pnl,
                )
                _current_trade_id = None
        else:
            logger.info("Holding %s | %s", active_position.ticker, exit_decision.detail)

        return  # don't look for entries while a position is open

    # -----------------------------------------------------------------------
    # Step 4 — Evaluate entry signal (no position open)
    # -----------------------------------------------------------------------
    entry = evaluate_entry(regime=regime, vix=vix, cfg=_cfg)

    # Always log the signal to Supabase for audit
    _db.insert_signal(entry)

    if entry.signal == Signal.BUY:
        buying_power = _alpaca.get_buying_power()
        shares = calculate_shares(
            price=entry.price,
            buying_power=buying_power,
            cfg=_cfg,
        )

        if shares > 0:
            logger.info(
                "Buying %d shares of %s @ $%.2f",
                shares, entry.ticker, entry.price,
            )
            _alpaca.buy(entry.ticker, shares)

            # Record the trade in Supabase
            _current_trade_id = _db.insert_trade(
                ticker=entry.ticker,
                entry_price=entry.price,
                shares=shares,
                entry_time=datetime.now(timezone.utc),
                regime=regime,
            )
        else:
            logger.warning("BUY signal but 0 shares calculated — skipping")
    else:
        logger.info("No entry signal | regime=%s | %s", regime.value, entry.reason)


def write_daily_summary():
    """
    Write end-of-day summary to Supabase. Called by scheduler at 4pm ET.
    """
    logger.info("Writing daily summary...")
    today = date.today()

    trades = _db.get_todays_trades(today)
    if not trades:
        logger.info("No trades today — skipping daily summary")
        return

    pnls = [t["pnl"] for t in trades if t.get("pnl") is not None]
    total_pnl = sum(pnls)
    winning = sum(1 for p in pnls if p > 0)
    losing = sum(1 for p in pnls if p <= 0)

    # Max drawdown = the worst single loss on the day (simplified)
    max_drawdown = min(pnls) if pnls else 0.0

    # Get current regime for the summary
    try:
        regime, vix, _, _ = detect_regime(
            vix_bear_threshold=_cfg.vix_bear_threshold,
            vix_bull_threshold=_cfg.vix_bull_threshold,
        )
        regime_str = regime.value
    except Exception:
        regime_str = "UNKNOWN"

    _db.upsert_daily_summary(
        trading_date=today,
        total_pnl=total_pnl,
        trades_taken=len(trades),
        winning_trades=winning,
        losing_trades=losing,
        max_drawdown=max_drawdown,
        regime_at_close=regime_str,
    )


def main():
    """Startup: load config, connect services, start scheduler."""
    global _cfg, _alpaca, _db, _limiter

    logger.info("Starting AI Trading Bot...")

    # Load and validate all env vars at startup — fails loudly if anything is missing
    _cfg = load_config()
    logger.info("Config loaded ✓")

    # Connect to Alpaca paper account
    _alpaca = AlpacaClient(_cfg)
    buying_power = _alpaca.get_buying_power()
    logger.info("Alpaca connected ✓ — buying power: $%.2f", buying_power)

    # Connect to Supabase
    _db = SupabaseDB(_cfg)
    logger.info("Supabase connected ✓")

    # Set up risk limiter
    _limiter = DailyLimiter(_cfg, _alpaca)

    # -----------------------------------------------------------------------
    # Scheduler setup
    # -----------------------------------------------------------------------
    # BlockingScheduler runs in the foreground — perfect for a Railway worker.
    # (BackgroundScheduler would let you do other things concurrently,
    #  but we don't need that here.)
    scheduler = BlockingScheduler(timezone=ET)

    # Main loop: every 5 minutes, Mon–Fri, 9:30am–3:50pm ET
    # CronTrigger with minute="*/5" fires at :00, :05, :10, etc.
    # day_of_week="mon-fri" skips weekends automatically.
    scheduler.add_job(
        run_loop,
        CronTrigger(
            day_of_week="mon-fri",
            hour="9-15",
            minute="30-59/5",  # 9:30, 9:35 ... 9:55
            timezone=ET,
        ),
        id="main_loop",
        name="5-minute trading loop",
    )
    # Cover 10am–3pm normally
    scheduler.add_job(
        run_loop,
        CronTrigger(
            day_of_week="mon-fri",
            hour="10-14",
            minute="*/5",
            timezone=ET,
        ),
        id="main_loop_full",
        name="5-minute trading loop (full hours)",
    )
    # 3pm–3:45pm ET
    scheduler.add_job(
        run_loop,
        CronTrigger(
            day_of_week="mon-fri",
            hour="15",
            minute="0,5,10,15,20,25,30,35,40,45",
            timezone=ET,
        ),
        id="main_loop_close",
        name="5-minute trading loop (close)",
    )

    # Daily summary at 4pm ET
    scheduler.add_job(
        write_daily_summary,
        CronTrigger(day_of_week="mon-fri", hour=16, minute=0, timezone=ET),
        id="daily_summary",
        name="Daily P&L summary",
    )

    logger.info("Scheduler started — running Mon–Fri 9:30am–3:45pm ET")
    logger.info("Press Ctrl+C to stop.")

    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")


if __name__ == "__main__":
    main()
