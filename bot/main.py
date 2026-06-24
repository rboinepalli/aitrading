"""
main.py — Momentum Scanner orchestrator.

Ties together the full pipeline:
  scanner → enricher → scorer → validator → telegram alert → human YES → trade → monitor → EOD

Called by scheduler.py (APScheduler runs this on Railway).
Can also be called directly: python main.py
"""
import logging
import sys
from datetime import datetime

import pytz

import db
import telegram_bot as tg
import monitor
from scanner import run_screen
from enricher import enrich_all
from scorer import score, rank
from validator import validate
from eod_job import run_eod
import alpaca_client as alpaca

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)
ET = pytz.timezone("America/New_York")


def run_scan(label: str = "SCAN") -> None:
    """
    Full scan pipeline: screen → enrich → score → validate → Telegram alert.
    Called at 9:15am (pre-market) and 9:45am (post-open confirmation).
    """
    if db.is_halted():
        logger.info("Trading halted — skipping scan")
        return

    now_str = datetime.now(ET).strftime("%b %d %I:%M %p ET")
    logger.info("=== %s: %s ===", label, now_str)

    # Step 1: Screen
    candidates = run_screen()
    if not candidates:
        tg.send(f"🔍 {label} — {now_str}\n\nNo candidates passed screening today.")
        return
    logger.info("Screen: %d candidates", len(candidates))

    # Step 2: Enrich
    enriched = enrich_all(candidates)
    if not enriched:
        tg.send(f"🔍 {label} — {now_str}\n\nCould not enrich any candidates.")
        return

    # Step 3: Score (initial, without catalyst)
    scored = [score(ind) for ind in enriched]
    pre_ranked = rank(scored)

    if not pre_ranked:
        tg.send(f"🔍 {label} — {now_str}\n\nNo picks met the minimum score threshold.")
        return
    logger.info("Scoring: %d/%d passed threshold", len(pre_ranked), len(scored))

    # Step 4: Validate (catalyst + sector ETF — top 5 only)
    validated = validate(pre_ranked[:5])

    # Log scan results to Supabase
    for s in validated:
        ind = s.indicators
        db.log_scan(
            ticker=s.ticker,
            score=s.score,
            rsi=ind.rsi,
            volume_ratio=ind.volume_ratio,
            price_at_scan=ind.price,
            ema9_above=ind.above_ema9,
            ema20_above=ind.above_ema20,
            vwap_above=ind.above_vwap,
            catalyst_found=s.catalyst_found,
            catalyst_text=s.catalyst_text,
            sector_etf=s.sector_etf,
            sector_etf_green=s.sector_etf_green,
        )

    # Step 5: Send Telegram alert — wait for YES approval
    tg.send_scan_results(validated, now_str)
    logger.info("Scan complete — sent %d picks to Telegram", len(validated))


def capture_spy_open() -> None:
    """Called at 9:30am to record SPY's open price for the circuit breaker."""
    quote = alpaca.get_quote("SPY")
    if quote:
        monitor.set_spy_open(quote.price)
        logger.info("SPY open: $%.2f", quote.price)


if __name__ == "__main__":
    # Manual run: python main.py scan | monitor | eod
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "scan"

    tg.start_listener()

    if cmd == "scan":
        run_scan("MANUAL SCAN")
    elif cmd == "monitor":
        monitor.poll()
    elif cmd == "eod":
        run_eod()
    else:
        print(f"Unknown command: {cmd}. Use: scan | monitor | eod")
