"""
scanner.py — Step 1: Screen candidates using Finnhub + Tier 1 watchlist.

Returns a deduplicated list of tickers that pass hard filters.
Expected output: 10–25 candidates for the enricher.
"""
import logging
from typing import Optional

import finnhub

from config import (
    FINNHUB_API_KEY, TIER1_WATCHLIST,
    FILTER_MIN_PRICE, FILTER_MIN_CHANGE_PCT,
    FILTER_MIN_AVG_VOLUME, FILTER_MIN_VOL_RATIO,
)

logger = logging.getLogger(__name__)
_fh = finnhub.Client(api_key=FINNHUB_API_KEY)


def _quote(ticker: str) -> Optional[dict]:
    """Fetch Finnhub quote. Returns dict with c/pc/dp/v keys or None."""
    try:
        q = _fh.quote(ticker)
        if not q or q.get("c", 0) == 0:
            return None
        return q
    except Exception as e:
        logger.warning("Finnhub quote(%s): %s", ticker, e)
        return None


def _passes_hard_filters(ticker: str, quote: dict) -> tuple[bool, str]:
    """
    Apply hard-filter checklist. Returns (passes, reason_if_failed).
    All conditions must be True for the ticker to be enriched.
    """
    price      = quote.get("c", 0)
    change_pct = quote.get("dp", 0)   # % change today
    volume     = quote.get("v", 0)    # today's volume

    if price < FILTER_MIN_PRICE:
        return False, f"price ${price:.2f} < ${FILTER_MIN_PRICE}"
    if change_pct < FILTER_MIN_CHANGE_PCT:
        return False, f"change {change_pct:.1f}% < {FILTER_MIN_CHANGE_PCT}%"
    if volume < FILTER_MIN_AVG_VOLUME * FILTER_MIN_VOL_RATIO:
        return False, f"volume {volume:,} too low"

    return True, ""


def run_screen() -> list[str]:
    """
    Combine Tier 1 watchlist + Tier 2 Finnhub movers.
    Apply hard filters and return deduplicated candidate list.
    """
    candidates: dict[str, dict] = {}

    # --- Tier 1: always scan the core watchlist ---
    logger.info("Screening Tier 1 watchlist (%d tickers)...", len(TIER1_WATCHLIST))
    for ticker in TIER1_WATCHLIST:
        q = _quote(ticker)
        if q:
            passes, reason = _passes_hard_filters(ticker, q)
            if passes:
                candidates[ticker] = q
                logger.debug("  ✓ %s (%.1f%%)", ticker, q.get("dp", 0))
            else:
                logger.debug("  ✗ %s — %s", ticker, reason)

    # --- Tier 2: broader liquid universe (catches breakouts outside core list) ---
    logger.info("Screening Tier 2 Finnhub gainers...")
    try:
        tier2_universe = [
            "RIVN", "LCID", "F", "GM", "NIO", "UBER", "LYFT", "SNAP", "PINS",
            "RBLX", "HOOD", "DKNG", "PENN", "CRWD", "PANW", "OKTA", "ZS",
            "NET", "DDOG", "MDB", "SNOW", "U", "ABNB", "DASH", "SHOP",
            "SQ", "PYPL", "AFRM", "UPST", "SOFI", "NU",
        ]
        for ticker in tier2_universe:
            if ticker in candidates:
                continue
            q = _quote(ticker)
            if q:
                passes, _ = _passes_hard_filters(ticker, q)
                if passes:
                    candidates[ticker] = q
                    logger.debug("  ✓ Tier2 %s (%.1f%%)", ticker, q.get("dp", 0))
    except Exception as e:
        logger.warning("Tier 2 scan error: %s", e)

    logger.info("Screen complete: %d candidates from %d checked",
                len(candidates), len(TIER1_WATCHLIST))
    return list(candidates.keys())
