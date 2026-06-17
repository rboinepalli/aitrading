"""
signals/scorer.py — Conviction scoring engine.

This is the heart of v2's signal quality improvement.

Instead of entering on 2 conditions (RSI + EMA), we score each ticker
across 6 signals worth 0–8 total points. A trade only executes if the
score meets the minimum threshold for the current time window.

Scoring table:
  RSI < 35              +2  (oversold, price dipped, bounce likely)
  Price > EMA20         +1  (intraday trend still intact)
  MACD bullish cross    +2  (momentum turning — strongest signal)
  Volume > 1.5x avg     +1  (real conviction behind the move)
  Price > VWAP          +1  (institutional buying pressure intraday)
  5-day uptrend         +1  (don't buy a multi-day downtrend)
  ─────────────────────────
  MAX SCORE             8

Thresholds:
  Primary window (9:30–11am):   need >= 5/8
  Power hour  (2pm–3:30pm):     need >= 6/8  (stricter — less time to recover)
  Dead zone   (11am–2pm):       NEVER enter

Why require multiple signals?
  Any single signal generates too many false positives on leveraged ETFs.
  Requiring 5/8 means at least momentum + oversold + one more confirmation
  must agree. This cuts trade frequency but dramatically improves win rate.
"""

import logging
from dataclasses import dataclass

from signals.indicators import IndicatorSnapshot, macd_crossed_above

logger = logging.getLogger(__name__)


@dataclass
class ConvictionScore:
    """
    Result of scoring a ticker.
    Includes the total score AND which individual signals fired —
    this gets stored in Supabase so you can audit why trades were taken.
    """
    ticker: str
    score: int                  # 0–8
    signals_fired: list[str]    # e.g. ["RSI", "EMA20", "MACD", "VOLUME"]
    signals_missed: list[str]   # e.g. ["VWAP", "5DAY"]
    rsi: float
    macd_line: float
    vwap: float
    volume_ratio: float
    price: float

    def summary(self) -> str:
        """Human-readable one-liner for logs and dashboard. e.g. 'TQQQ 6/8 ✓RSI ✓MACD ✗VWAP'"""
        fired = " ".join(f"✓{s}" for s in self.signals_fired)
        missed = " ".join(f"✗{s}" for s in self.signals_missed)
        return f"{self.ticker} {self.score}/8  {fired}  {missed}".strip()


def score_ticker(
    snap: IndicatorSnapshot,
    rsi_oversold: float,
    volume_ratio_threshold: float,
) -> ConvictionScore:
    """
    Score a single ticker against all 6 conviction signals.

    Args:
        snap:                   Pre-computed indicators for the ticker
        rsi_oversold:           RSI threshold (default 35)
        volume_ratio_threshold: Volume multiplier (default 1.5)

    Returns:
        ConvictionScore with total points and which signals fired.
    """
    score = 0
    fired = []
    missed = []

    # -----------------------------------------------------------------------
    # Signal 1 & 2: RSI oversold (+2 points)
    # Worth double because oversold + bounce is the core thesis.
    # -----------------------------------------------------------------------
    if snap.rsi < rsi_oversold:
        score += 2
        fired.append("RSI")
    else:
        missed.append("RSI")

    # -----------------------------------------------------------------------
    # Signal 3: Price above EMA20 (+1 point)
    # Ensures we're buying a pullback in an uptrend, not a falling knife.
    # -----------------------------------------------------------------------
    if snap.price > snap.ema_20:
        score += 1
        fired.append("EMA20")
    else:
        missed.append("EMA20")

    # -----------------------------------------------------------------------
    # Signal 4 & 5: MACD bullish crossover (+2 points)
    # The single strongest momentum signal we have.
    # MACD crossing above its signal line = momentum turning positive.
    # -----------------------------------------------------------------------
    if macd_crossed_above(snap):
        score += 2
        fired.append("MACD")
    else:
        missed.append("MACD")

    # -----------------------------------------------------------------------
    # Signal 6: Volume spike (+1 point)
    # High volume = the move has institutional participation.
    # Low volume moves frequently reverse.
    # -----------------------------------------------------------------------
    if snap.volume_ratio >= volume_ratio_threshold:
        score += 1
        fired.append("VOLUME")
    else:
        missed.append("VOLUME")

    # -----------------------------------------------------------------------
    # Signal 7: Price above VWAP (+1 point)
    # VWAP is the "fair price" for the day based on all transactions.
    # Price > VWAP = net buying pressure so far today.
    # -----------------------------------------------------------------------
    if snap.price > snap.vwap:
        score += 1
        fired.append("VWAP")
    else:
        missed.append("VWAP")

    # -----------------------------------------------------------------------
    # Signal 8: 5-day uptrend (+1 point)
    # Don't buy a multi-day downtrend expecting a reversal.
    # If price is lower than 5 days ago, the trend is down.
    # -----------------------------------------------------------------------
    if snap.five_day_trend:
        score += 1
        fired.append("5DAY")
    else:
        missed.append("5DAY")

    result = ConvictionScore(
        ticker=snap.ticker,
        score=score,
        signals_fired=fired,
        signals_missed=missed,
        rsi=snap.rsi,
        macd_line=snap.macd_line,
        vwap=snap.vwap,
        volume_ratio=snap.volume_ratio,
        price=snap.price,
    )
    logger.info("Scored %s", result.summary())
    return result


def pick_best_ticker(scores: list[ConvictionScore], min_score: int) -> ConvictionScore | None:
    """
    From a list of scored tickers, return the highest scorer that meets
    the minimum threshold. Returns None if no ticker qualifies.

    Used by Strategy B to pick the single best ticker to trade each day.
    """
    eligible = [s for s in scores if s.score >= min_score]
    if not eligible:
        return None
    # Sort descending by score; ties broken by higher RSI score first
    return sorted(eligible, key=lambda s: s.score, reverse=True)[0]
