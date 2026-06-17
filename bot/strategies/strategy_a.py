"""
strategies/strategy_a.py — aggressive_3x strategy.

Trades 3x leveraged ETFs:
  BULL regime → TQQQ (3x QQQ bull)
  BEAR regime → SQQQ (3x QQQ bear)
  CHOPPY      → sits out

Why 3x leveraged ETFs?
  TQQQ moves 3x what the QQQ (Nasdaq 100) moves in a day.
  A +2% QQQ day = roughly +6% TQQQ day.
  This amplification means our +15% take profit target only requires
  the underlying index to move +5% — achievable in a strong trend day.

  The risk: losses are also amplified 3x, which is why:
  - Stop loss is tight (-10%)
  - Partial exit at +8% locks in profit and moves stop to breakeven
  - Hard EOD close at 3:45pm prevents overnight decay
"""

import logging
from dataclasses import dataclass

from config import Config, StrategyConfig
from data.market_data import MarketDataClient
from signals.indicators import fetch_indicators
from signals.regime import Regime
from signals.scorer import score_ticker, ConvictionScore

logger = logging.getLogger(__name__)


def get_ticker_for_regime(regime: Regime, cfg: Config) -> str | None:
    """
    Return which ticker Strategy A should trade given the current regime.
    Returns None if regime is CHOPPY (sit out).
    """
    if regime == Regime.BULL:
        return cfg.strategy_a.tickers[0]  # TQQQ
    elif regime == Regime.BEAR:
        return cfg.strategy_a.tickers[1]  # SQQQ
    else:
        return None  # CHOPPY — sit out


def evaluate_strategy_a(
    regime: Regime,
    vix: float,
    min_score: int,
    cfg: Config,
    data_client: MarketDataClient,
) -> ConvictionScore | None:
    """
    Score the appropriate ticker for Strategy A given the current regime.

    Args:
        regime:    Current market regime
        vix:       Current VIX (for logging context)
        min_score: Minimum conviction score required (5 primary, 6 power hour)
        cfg:       Bot configuration

    Returns:
        ConvictionScore if score >= min_score, else None (don't trade)
    """
    ticker = get_ticker_for_regime(regime, cfg)

    if ticker is None:
        logger.info("Strategy A: CHOPPY regime — sitting out")
        return None

    snap = fetch_indicators(ticker, data_client=data_client, rsi_period=cfg.rsi_period)
    if snap is None:
        logger.warning("Strategy A: Could not fetch indicators for %s", ticker)
        return None

    conviction = score_ticker(snap, cfg.rsi_oversold, cfg.volume_ratio_threshold)

    if conviction.score >= min_score:
        logger.info(
            "Strategy A: ENTRY SIGNAL — %s score=%d/%d | VIX=%.1f",
            conviction.summary(), conviction.score, min_score, vix,
        )
        return conviction

    logger.info(
        "Strategy A: No entry — %s (need %d, got %d)",
        conviction.summary(), min_score, conviction.score,
    )
    return None
