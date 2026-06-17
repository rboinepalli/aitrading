"""
strategies/strategy_b.py — conservative_multi strategy.

Trades large-cap stocks and broad ETFs in BULL regime only.
Picks the single highest-scoring ticker each day.

Tickers: QQQ, NVDA, AAPL, MSFT, AMD, SPY

Why these tickers?
  - QQQ / SPY: broad market ETFs — safest, lowest individual risk
  - NVDA / AAPL / MSFT: highest liquidity mega-caps, tight spreads
  - AMD: more volatile, can score higher on momentum signals

Why BULL only?
  These are LONG positions only. In a BEAR regime, buying QQQ or NVDA
  means fighting the trend. Strategy B sits out completely in BEAR/CHOPPY
  rather than going short (that's Strategy A's job with SQQQ).

Partial exit at +3%:
  Non-leveraged stocks move more slowly than 3x ETFs.
  +3% on NVDA is a very strong intraday move. We lock in half there
  and let the rest run to the +5% target.
"""

import logging

from config import Config
from signals.indicators import fetch_indicators
from signals.regime import Regime
from signals.scorer import score_ticker, pick_best_ticker, ConvictionScore

logger = logging.getLogger(__name__)

# Strategy B only trades in BULL regime
BULL_ONLY = [Regime.BULL]


def evaluate_strategy_b(
    regime: Regime,
    min_score: int,
    cfg: Config,
) -> ConvictionScore | None:
    """
    Score all Strategy B tickers and return the highest scorer if it
    meets the minimum conviction threshold.

    In BEAR or CHOPPY → returns None immediately (sits out).
    In BULL → scores all 6 tickers, picks the best one.

    Args:
        regime:    Current market regime
        min_score: Minimum score to enter (5 primary, 6 power hour)
        cfg:       Bot configuration

    Returns:
        ConvictionScore for the best ticker, or None if none qualify
    """
    if regime != Regime.BULL:
        logger.info(
            "Strategy B: regime=%s — sitting out (BULL only)", regime.value
        )
        return None

    scores = []
    for ticker in cfg.strategy_b.tickers:
        snap = fetch_indicators(ticker, rsi_period=cfg.rsi_period)
        if snap is None:
            logger.warning("Strategy B: Could not fetch %s — skipping", ticker)
            continue
        conviction = score_ticker(snap, cfg.rsi_oversold, cfg.volume_ratio_threshold)
        scores.append(conviction)

    if not scores:
        logger.warning("Strategy B: No indicator data available for any ticker")
        return None

    # Log scores for all tickers (visible in Railway logs + useful for tuning)
    logger.info("Strategy B scores:")
    for s in sorted(scores, key=lambda x: x.score, reverse=True):
        logger.info("  %s", s.summary())

    best = pick_best_ticker(scores, min_score)

    if best:
        logger.info(
            "Strategy B: ENTRY SIGNAL — %s (score %d >= %d)",
            best.ticker, best.score, min_score,
        )
    else:
        top = max(scores, key=lambda s: s.score)
        logger.info(
            "Strategy B: No entry — best was %s score=%d (need %d)",
            top.ticker, top.score, min_score,
        )

    return best
