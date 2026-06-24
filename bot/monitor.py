"""
monitor.py — 30-minute polling loop: check exit signals + circuit breakers.

Runs every 30 minutes during market hours (10am–3:30pm ET).
Also called at 3:45pm for forced EOD close.

Exit signals checked (in priority order):
  1. SPY circuit breaker (-1.5% from open) → exit ALL, halt trading
  2. Daily loss limit ($200) → halt new trades
  3. Stop loss hit
  4. RSI overbought (> 72)
  5. Take profit target hit
  6. EOD force close (3:45pm)
"""
import logging
from datetime import datetime, timezone

import pytz

import alpaca_client as alpaca
import db
import telegram_bot as tg
from config import (
    SPY_CIRCUIT_PCT, DAILY_LOSS_LIMIT, RSI_EXIT_THRESHOLD,
    HOLD_MAX_DAYS,
)
from enricher import enrich

logger = logging.getLogger(__name__)
ET = pytz.timezone("America/New_York")

# SPY open price — set at 9:30am, used for circuit breaker check
_spy_open_price: float = 0.0


def set_spy_open(price: float) -> None:
    global _spy_open_price
    _spy_open_price = price
    logger.info("SPY open price set: $%.2f", price)


def _check_spy_circuit() -> bool:
    """
    Return True if SPY has dropped more than SPY_CIRCUIT_PCT from today's open.
    Triggers a halt and force-exit of all positions.
    """
    if _spy_open_price <= 0:
        return False
    spy_quote = alpaca.get_quote("SPY")
    if not spy_quote:
        return False
    change_pct = (spy_quote.price - _spy_open_price) / _spy_open_price * 100
    if change_pct <= SPY_CIRCUIT_PCT:
        logger.warning("SPY circuit breaker: %.2f%% from open", change_pct)
        return True
    return False


def _check_daily_loss() -> bool:
    """Return True if daily loss limit has been exceeded."""
    daily_loss = db.get_daily_loss()
    if daily_loss <= -DAILY_LOSS_LIMIT:
        reason = f"Daily loss limit hit: ${daily_loss:.2f}"
        db.halt_trading(reason)
        tg.send_circuit_breaker(reason)
        return True
    return False


def _exit_trade(trade: dict, exit_price: float, reason: str) -> None:
    """Close a trade: sell on Alpaca, update DB, send Telegram alert."""
    ticker   = trade["ticker"]
    trade_id = trade["id"]
    shares   = int(trade["shares"])
    entry    = float(trade["entry_price"])

    entry_dt = datetime.fromisoformat(trade["entry_time"].replace("Z", "+00:00"))
    hold_hrs = (datetime.now(timezone.utc) - entry_dt).total_seconds() / 3600

    alpaca.sell(ticker, shares, reason=reason)
    db.close_trade(trade_id, exit_price, reason, hold_hrs)

    pnl = (exit_price - entry) * shares
    db.add_daily_loss(-pnl if pnl < 0 else 0)   # only count losses toward daily limit
    db.set_state("positions_open", str(max(0, int(db.get_state("positions_open", "0")) - 1)))

    tg.send_exit_alert(ticker, shares, entry, exit_price, reason, pnl)


def poll(force_eod: bool = False) -> None:
    """
    Main poll function — called every 30 minutes and at 3:45pm EOD.
    Checks circuit breakers then evaluates each open position.
    """
    if db.is_halted() and not force_eod:
        logger.info("Trading halted — skipping poll")
        return

    now_et = datetime.now(ET)
    logger.info("=== Monitor poll: %s ET ===", now_et.strftime("%H:%M"))

    # --- SPY circuit breaker ---
    if _check_spy_circuit():
        logger.warning("SPY circuit breaker triggered — exiting all positions")
        db.halt_trading("SPY dropped 1.5%+ from open")
        tg.send_circuit_breaker("SPY dropped 1.5%+ from open — all positions exited")
        force_eod = True   # treat as EOD — exit everything

    open_trades = db.get_open_trades()
    if not open_trades:
        logger.info("No open positions to monitor")
        return

    logger.info("Monitoring %d open position(s)", len(open_trades))

    for trade in open_trades:
        ticker   = trade["ticker"]
        entry    = float(trade["entry_price"])
        stop     = float(trade["stop_loss"])
        target   = float(trade["target"])

        # Check hold time — force close after HOLD_MAX_DAYS
        entry_dt = datetime.fromisoformat(trade["entry_time"].replace("Z", "+00:00"))
        hold_days = (datetime.now(timezone.utc) - entry_dt).days

        # Get current price
        quote = alpaca.get_quote(ticker)
        if not quote:
            logger.warning("Cannot get quote for %s — skipping", ticker)
            continue
        price = quote.price

        exit_price  = price
        exit_reason = None

        # EOD force close
        if force_eod:
            exit_reason = "force_eod"

        # Max hold days
        elif hold_days >= HOLD_MAX_DAYS:
            exit_reason = "force_eod"
            logger.info("%s held %d days — forcing close", ticker, hold_days)

        # Stop loss
        elif price <= stop:
            exit_reason = "stop_hit"
            logger.info("%s stop hit: $%.2f <= stop $%.2f", ticker, price, stop)

        # Target hit
        elif price >= target:
            exit_reason = "target_hit"
            logger.info("%s target hit: $%.2f >= target $%.2f", ticker, price, target)

        # RSI overbought exit
        else:
            ind = enrich(ticker)
            if ind and ind.rsi > RSI_EXIT_THRESHOLD:
                exit_reason = "rsi_exit"
                logger.info("%s RSI exit: %.1f > %.1f", ticker, ind.rsi, RSI_EXIT_THRESHOLD)

        if exit_reason:
            _exit_trade(trade, exit_price, exit_reason)
        else:
            pnl_pct = (price - entry) / entry * 100
            logger.info("Holding %s @ $%.2f | entry=$%.2f | P&L: %+.1f%% | stop=$%.2f target=$%.2f",
                        ticker, price, entry, pnl_pct, stop, target)

    # After processing all trades, check daily loss limit
    _check_daily_loss()
