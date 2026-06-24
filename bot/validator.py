"""
validator.py — Step 4: Validate catalysts via Finnhub news.

For top candidates, checks:
  1. Finnhub company news for today → extract headline + category
  2. Identify catalyst type (earnings, upgrade, partnership, etc.)
  3. Check sector ETF direction via Alpaca quote

Returns enriched ScoredTicker objects with catalyst_found/catalyst_text filled in.
"""
import logging
from datetime import date, timedelta
from typing import Optional

import finnhub

import alpaca_client as alpaca
from config import FINNHUB_API_KEY, SECTOR_ETFS
from scorer import ScoredTicker

logger = logging.getLogger(__name__)
_fh = finnhub.Client(api_key=FINNHUB_API_KEY)

# Keywords that indicate a meaningful catalyst
CATALYST_KEYWORDS = [
    "earnings", "beat", "guidance", "upgrade", "downgrade", "price target",
    "partnership", "contract", "acquisition", "merger", "fda", "approval",
    "revenue", "raised", "analyst", "initiated", "overweight", "buy rating",
    "short squeeze", "buyback", "dividend",
]


def _find_catalyst(ticker: str) -> tuple[bool, str]:
    """
    Check Finnhub news for today. Returns (found, headline_text).
    """
    today     = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    try:
        news = _fh.company_news(ticker, _from=yesterday, to=today)
        if not news:
            return False, ""
        # Find the most relevant headline
        for article in news[:10]:
            headline = (article.get("headline") or "").lower()
            summary  = (article.get("summary")  or "").lower()
            text     = headline + " " + summary
            for kw in CATALYST_KEYWORDS:
                if kw in text:
                    return True, article.get("headline", "")[:200]
        # News exists but no strong keyword — still return first headline
        return False, news[0].get("headline", "")[:200] if news else ""
    except Exception as e:
        logger.warning("Finnhub news(%s): %s", ticker, e)
        return False, ""


def _sector_etf_green(ticker: str) -> tuple[str, bool]:
    """Check if the stock's sector ETF is positive today. Returns (etf_symbol, is_green)."""
    etf = SECTOR_ETFS.get(ticker, "QQQ")
    quote = alpaca.get_quote(etf)
    if not quote:
        return etf, False
    # Compare to previous close via daily bars
    daily = alpaca.get_daily_bars(etf, limit=3)
    if daily is None or len(daily) < 2:
        return etf, False
    prev_close = float(daily["Close"].iloc[-2])
    is_green   = quote.price > prev_close
    return etf, is_green


def validate(candidates: list[ScoredTicker]) -> list[ScoredTicker]:
    """
    Enrich top candidates (score ≥ threshold) with catalyst + sector ETF data.
    Mutates the ScoredTicker objects in place and returns them re-ranked.
    """
    from scorer import rank as re_rank, score as rescore
    import scorer

    validated = []
    for s in candidates:
        ticker = s.ticker
        logger.info("Validating %s...", ticker)

        # Catalyst check
        found, text = _find_catalyst(ticker)
        s.catalyst_found = found
        s.catalyst_text  = text

        # Sector ETF check
        etf, is_green    = _sector_etf_green(ticker)
        s.sector_etf     = etf
        s.sector_etf_green = is_green

        # Rescore with catalyst + sector info now filled in
        rescored = scorer.score(
            s.indicators,
            catalyst_found=found,
            sector_etf_green=is_green,
            sector_etf=etf,
        )
        rescored.catalyst_text = text

        if not rescored.disqualified:
            validated.append(rescored)
            logger.info("  %s — score=%d catalyst=%s sector_etf=%s(%s)",
                        ticker, rescored.score,
                        "✓" if found else "✗",
                        etf, "green" if is_green else "red")

    return re_rank(validated)
