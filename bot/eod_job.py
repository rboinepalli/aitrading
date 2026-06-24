"""
eod_job.py — End-of-day tasks (runs at 4:00pm ET and next-day fill).

Tasks:
  1. Force-close any remaining open positions (safety net)
  2. Fill price_1day_later and price_2days_later on old scan rows
  3. Write daily_summary to Supabase
  4. Send daily P&L summary to Telegram
  5. Reset daily state (loss counter, halt flag)
"""
import logging
from datetime import date, datetime, timezone

import alpaca_client as alpaca
import db
import monitor
import telegram_bot as tg

logger = logging.getLogger(__name__)


def force_close_all() -> None:
    """Safety net: close any positions still open at EOD."""
    monitor.poll(force_eod=True)


def fill_past_scan_prices() -> None:
    """
    For any scan rows where price_1day_later or price_2days_later is NULL,
    fetch the current price and fill it in.
    Called daily — prices become available after 1 or 2 trading days.
    """
    unfilled = db.get_unfilled_scans(days_ago=1)
    if not unfilled:
        return

    logger.info("Filling prices for %d old scan rows...", len(unfilled))
    for row in unfilled:
        ticker  = row["ticker"]
        quote   = alpaca.get_quote(ticker)
        if not quote:
            continue
        price = quote.price

        p1d = price if row.get("price_1day_later") is None else None
        p2d = price if row.get("price_2days_later") is None else None

        if p1d is not None or p2d is not None:
            db.fill_scan_prices(row["id"], p1d, p2d)
            logger.debug("Filled %s: 1d=$%.2f 2d=$%.2f", ticker, price, price)


def write_daily_summary() -> None:
    """Aggregate today's closed trades and write daily_summary row."""
    trades = db.get_todays_closed_trades()
    if not trades:
        logger.info("No trades today — skipping daily summary")
        return

    pnls        = [float(t.get("pnl_dollars") or 0) for t in trades]
    total_pnl   = sum(pnls)
    wins        = sum(1 for p in pnls if p > 0)
    losses      = len(pnls) - wins
    best_ticker  = max(trades, key=lambda t: t.get("pnl_dollars") or 0)["ticker"] if trades else ""
    worst_ticker = min(trades, key=lambda t: t.get("pnl_dollars") or 0)["ticker"] if trades else ""

    db.upsert_daily_summary(
        trading_date=date.today(),
        trades_taken=len(trades),
        trades_won=wins,
        trades_lost=losses,
        total_pnl=total_pnl,
        avg_hold_hrs=0,
        best_ticker=best_ticker,
        worst_ticker=worst_ticker,
    )
    logger.info("Daily summary written: %d trades P&L=$%.2f", len(trades), total_pnl)
    tg.send_daily_summary(date.today().isoformat(), total_pnl, wins, losses)


def run_eod() -> None:
    """Full EOD sequence — called at 4:00pm ET."""
    logger.info("=== EOD job starting ===")
    force_close_all()
    fill_past_scan_prices()
    write_daily_summary()
    db.reset_daily_state()
    logger.info("=== EOD job complete ===")
