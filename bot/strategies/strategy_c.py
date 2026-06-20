"""
strategies/strategy_c.py — aggressive_semis strategy.

Trades 3x leveraged semiconductor ETFs:
  BULL regime → SOXL (3x Semiconductors bull — SOXX index * 3)
  BEAR regime → SOXS (3x Semiconductors bear — inverse SOXX * 3)

Why semiconductors?
  Semiconductors (NVDA, AMD, INTC, AVGO, etc.) are the most volatile
  sector within the Nasdaq. They lead the market — SOXL often moves
  2–3x more than TQQQ on a given day.

  On a strong BULL day where TQQQ might gain +6%, SOXL can gain +10–15%.
  This makes it the highest risk/reward strategy in the bot.

Why min score 6/8 always (even in PRIMARY window)?
  Because SOXL is so volatile, a false signal is expensive. We require
  6/8 signals in BOTH windows to ensure high conviction before entering.
  In Strategy A, PRIMARY only needs 5/8 — but SOXL deserves a stricter bar.

Capital note:
  Budget starts at $5,000 (half of A/B). The 3x leverage means $5k in SOXL
  gives you the price exposure of $15k worth of the underlying index.
"""

import logging

from config import Config, StrategyConfig
from data.market_data import MarketDataClient
from signals.indicators import fetch_indicators
from signals.regime import Regime
from signals.scorer import score_ticker, ConvictionScore

logger = logging.getLogger(__name__)


def get_ticker_for_regime(regime: Regime, cfg: Config) -> str | None:
    """
    Return which ticker Strategy C should trade given the current regime.
    Returns None if regime is CHOPPY (sit out — semis are too volatile in choppy markets).
    """
    if regime == Regime.BULL:
        return cfg.strategy_c.tickers[0]  # SOXL
    elif regime == Regime.BEAR:
        return cfg.strategy_c.tickers[1]  # SOXS
    else:
        return None  # CHOPPY — sit out


def evaluate_strategy_c(
    regime: Regime,
    vix: float,
    min_score: int,
    cfg: Config,
    data_client: MarketDataClient,
) -> ConvictionScore | None:
    """
    Score the appropriate semiconductor ETF for Strategy C.

    Args:
        regime:    Current market regime (BULL → SOXL, BEAR → SOXS)
        vix:       Current VIXY price (for logging context only)
        min_score: Minimum conviction score required (always 6 for Strategy C)
        cfg:       Bot configuration

    Returns:
        ConvictionScore if score >= min_score, else None
    """
    # Strategy C always enforces its own stricter min score
    effective_min = max(min_score, cfg.strategy_c.primary_min_score)

    ticker = get_ticker_for_regime(regime, cfg)

    if ticker is None:
        logger.info("Strategy C: CHOPPY regime — sitting out (too volatile for unclear markets)")
        return None

    snap = fetch_indicators(ticker, data_client=data_client, rsi_period=cfg.rsi_period)
    if snap is None:
        logger.warning("Strategy C: Could not fetch indicators for %s", ticker)
        return None

    conviction = score_ticker(snap, cfg.rsi_oversold, cfg.volume_ratio_threshold)

    if conviction.score >= effective_min:
        logger.info(
            "Strategy C: ENTRY SIGNAL — %s score=%d/%d | VIXY=%.1f",
            conviction.summary(), conviction.score, effective_min, vix,
        )
        return conviction

    logger.info(
        "Strategy C: No entry — %s (need %d, got %d)",
        conviction.summary(), effective_min, conviction.score,
    )
    return None
