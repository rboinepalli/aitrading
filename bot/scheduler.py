"""
scheduler.py — APScheduler entry point for Railway deployment.

Schedule (all times ET, Mon–Fri):
  9:15 AM   Pre-market scan (gap ups, volume leaders)
  9:30 AM   Capture SPY open price for circuit breaker
  9:45 AM   Post-open confirmation scan (who held the move)
  10:00 AM  Reset daily state (loss counter, halt flag)
  Every 30m (10:00 AM – 3:30 PM)   Monitor open positions
  3:45 PM   Force EOD close (safety net)
  4:00 PM   EOD job (fill scan prices, daily summary, reset state)
"""
import logging
import sys

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

import telegram_bot as tg
from main import run_scan, capture_spy_open
from monitor import poll
from eod_job import run_eod
import db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)
ET = pytz.timezone("America/New_York")


def main():
    logger.info("Starting Momentum Scanner Bot...")

    # Start Telegram listener in background thread
    tg.start_listener()
    tg.send("🤖 <b>Momentum Scanner Bot started</b>\n/stats — today's P&L\n/positions — open trades")

    scheduler = BlockingScheduler(timezone=ET)

    # 9:15am — pre-market scan
    scheduler.add_job(
        lambda: run_scan("PRE-MARKET SCAN"),
        CronTrigger(day_of_week="mon-fri", hour=9, minute=15, timezone=ET),
        id="premarket_scan",
    )

    # 9:30am — capture SPY open
    scheduler.add_job(
        capture_spy_open,
        CronTrigger(day_of_week="mon-fri", hour=9, minute=30, timezone=ET),
        id="spy_open",
    )

    # 9:45am — post-open confirmation scan
    scheduler.add_job(
        lambda: run_scan("POST-OPEN SCAN"),
        CronTrigger(day_of_week="mon-fri", hour=9, minute=45, timezone=ET),
        id="postopen_scan",
    )

    # 10:00am — reset daily state (ensures clean slate each morning)
    scheduler.add_job(
        db.reset_daily_state,
        CronTrigger(day_of_week="mon-fri", hour=10, minute=0, timezone=ET),
        id="daily_reset",
    )

    # Every 30 min 10am–3:30pm — monitor open positions
    scheduler.add_job(
        poll,
        CronTrigger(day_of_week="mon-fri", hour="10-15", minute="0,30", timezone=ET),
        id="monitor",
    )

    # 3:45pm — force EOD close
    scheduler.add_job(
        lambda: poll(force_eod=True),
        CronTrigger(day_of_week="mon-fri", hour=15, minute=45, timezone=ET),
        id="force_eod",
    )

    # 4:00pm — EOD job
    scheduler.add_job(
        run_eod,
        CronTrigger(day_of_week="mon-fri", hour=16, minute=0, timezone=ET),
        id="eod_job",
    )

    logger.info("Scheduler running — Mon–Fri ET")
    logger.info("Scans: 9:15am (pre) + 9:45am (post-open)")
    logger.info("Monitor: every 30min 10am–3:30pm")
    logger.info("EOD close: 3:45pm | EOD job: 4:00pm")

    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("Bot stopped.")
        tg.send("🛑 Bot stopped.")


if __name__ == "__main__":
    main()
