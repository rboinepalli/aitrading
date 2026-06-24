"""
scorer.py — Step 3: Score each enriched ticker 0–100.

Scoring table (115 raw points → normalized to 100):
  Volume surge       25 pts   1.5x=10, 2x=18, 3x+=25
  Price momentum     20 pts   +1.5%=8, +3%=15, +5%+=20
  EMA position       10 pts   above EMA9=5, also above EMA20=+5
  VWAP position      10 pts   price > VWAP = 10
  RSI sweet spot     15 pts   52–58=10, 58–65=15, 65–70=8
  News catalyst      15 pts   confirmed catalyst = 15
  Sector tailwind    10 pts   sector ETF green today = 10
  Pre-market gap     10 pts   gapped up and held open = 10

Hard disqualifiers (any one → skip entirely):
  RSI > 70             overbought, chasing
  RSI < 45             no momentum
  Price below EMA9     trend not confirmed
  Price below VWAP     net selling pressure
  Volume ratio < 1.5x  no conviction
  Already up 8%+       never chase
"""
import logging
from dataclasses import dataclass, field
from typing import Optional

from enricher import Indicators
from config import NO_CHASE_PCT, MIN_SCORE

logger = logging.getLogger(__name__)

MAX_RAW = 115  # sum of all component maxes


@dataclass
class ScoredTicker:
    ticker: str
    score: int              # 0–100 normalized
    raw_score: int
    disqualified: bool
    disqualify_reason: str
    indicators: Indicators
    catalyst_found: bool    # filled by validator
    catalyst_text: str      # filled by validator
    sector_etf: str         # filled by validator
    sector_etf_green: bool  # filled by validator
    # Computed trade levels (filled by scorer after ATR available)
    entry_price: float = 0.0
    stop_loss: float   = 0.0
    target: float      = 0.0
    rr_ratio: float    = 0.0


def score(ind: Indicators, catalyst_found: bool = False,
          sector_etf_green: bool = False, sector_etf: str = "",
          premarket_gap_held: bool = False) -> ScoredTicker:
    """
    Score a single ticker. Disqualifiers are checked first.
    Returns a ScoredTicker — check .disqualified before using .score.
    """
    base = ScoredTicker(
        ticker=ind.ticker, score=0, raw_score=0,
        disqualified=False, disqualify_reason="",
        indicators=ind,
        catalyst_found=catalyst_found, catalyst_text="",
        sector_etf=sector_etf, sector_etf_green=sector_etf_green,
    )

    # --- Hard disqualifiers ---
    if ind.rsi > 70:
        base.disqualified = True
        base.disqualify_reason = f"RSI {ind.rsi:.1f} > 70 (overbought)"
        return base
    if ind.rsi < 45:
        base.disqualified = True
        base.disqualify_reason = f"RSI {ind.rsi:.1f} < 45 (no momentum)"
        return base
    if not ind.above_ema9:
        base.disqualified = True
        base.disqualify_reason = f"price ${ind.price:.2f} below EMA9 ${ind.ema9:.2f}"
        return base
    if not ind.above_vwap:
        base.disqualified = True
        base.disqualify_reason = f"price ${ind.price:.2f} below VWAP ${ind.vwap:.2f}"
        return base
    if ind.volume_ratio < 1.5:
        base.disqualified = True
        base.disqualify_reason = f"volume ratio {ind.volume_ratio:.1f}x < 1.5x"
        return base
    if ind.change_pct >= NO_CHASE_PCT:
        base.disqualified = True
        base.disqualify_reason = f"already up {ind.change_pct:.1f}% — no chasing"
        return base

    # --- Scoring ---
    raw = 0

    # Volume surge (25 pts)
    if ind.volume_ratio >= 3.0:   raw += 25
    elif ind.volume_ratio >= 2.0: raw += 18
    elif ind.volume_ratio >= 1.5: raw += 10

    # Price momentum (20 pts)
    pct = ind.change_pct
    if pct >= 5.0:   raw += 20
    elif pct >= 3.0: raw += 15
    elif pct >= 1.5: raw +=  8

    # EMA position (10 pts)
    if ind.above_ema9:  raw += 5
    if ind.above_ema20: raw += 5

    # VWAP position (10 pts)
    if ind.above_vwap: raw += 10

    # RSI sweet spot (15 pts)
    rsi = ind.rsi
    if 58 <= rsi <= 65:   raw += 15
    elif 52 <= rsi < 58:  raw += 10
    elif 65 < rsi <= 70:  raw +=  8

    # News catalyst (15 pts)
    if catalyst_found: raw += 15

    # Sector tailwind (10 pts)
    if sector_etf_green: raw += 10

    # Pre-market gap held (10 pts)
    if premarket_gap_held: raw += 10

    normalized = round(raw / MAX_RAW * 100)

    # --- ATR-based entry / stop / target ---
    entry  = ind.price
    stop   = round(entry - ind.atr, 4) if ind.atr > 0 else round(entry * 0.978, 4)
    target = round(entry + 2 * ind.atr, 4) if ind.atr > 0 else round(entry * 1.044, 4)
    rr     = round((target - entry) / (entry - stop), 2) if entry > stop else 2.0

    base.score       = normalized
    base.raw_score   = raw
    base.entry_price = round(entry, 4)
    base.stop_loss   = stop
    base.target      = target
    base.rr_ratio    = rr

    return base


def rank(scored: list[ScoredTicker]) -> list[ScoredTicker]:
    """Filter disqualified and below-minimum-score, sort by score descending."""
    eligible = [s for s in scored if not s.disqualified and s.score >= MIN_SCORE]
    return sorted(eligible, key=lambda s: s.score, reverse=True)
