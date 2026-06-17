"""
signals/regime.py — Market regime detection (v4 — simplified).

Direction comes from SPY's 200-day moving average only:
  SPY price > 200-DMA  →  BULL  (uptrend — buy TQQQ / multi-stock)
  SPY price < 200-DMA  →  BEAR  (downtrend — buy SQQQ only)

No CHOPPY, no VIX gate.

Why no VIX?
  VIX-based gates were blocking valid trading days because we only had
  yesterday's VIX (CBOE CSV is EOD only) and VIXY has volatility decay
  that makes thresholds drift over time.

  More importantly, our conviction scoring system (5/8 signals: RSI,
  MACD, VWAP, volume, EMA, 5-day trend) already measures market quality
  directly on the ticker we want to trade. In a genuinely choppy or fearful
  market, these signals won't all fire simultaneously and the score stays
  below the 5-point threshold — so we sit out anyway.

  VIXY price is still fetched and logged alongside every signal for audit,
  but it never blocks a trade.

Why 200-DMA?
  The 200-day SMA is the most widely watched institutional trend filter.
  Above it = healthy uptrend. Below it = risk-off. It gives us direction
  (TQQQ vs SQQQ for Strategy A) without noisy day-to-day VIX fluctuations.
"""

import logging
from enum import Enum

from data.market_data import MarketDataClient

logger = logging.getLogger(__name__)


class Regime(str, Enum):
    """
    BULL or BEAR — determined by SPY vs its 200-day SMA.
    TypeScript analogy: type Regime = 'BULL' | 'BEAR'
    """
    BULL = "BULL"
    BEAR = "BEAR"


def detect_regime(
    data_client: MarketDataClient,
) -> tuple[Regime, float, float, float]:
    """
    Determine BULL or BEAR regime from SPY's 200-day moving average.

    Args:
        data_client: shared MarketDataClient (Alpaca IEX)

    Returns:
        (regime, vixy_price, spy_price, spy_sma_200)
        vixy_price is for audit logging — does not affect regime.

    Raises:
        RuntimeError if SPY data is unavailable (retries next tick).
    """
    spy_daily = data_client.get_daily_bars("SPY", days=320)

    if spy_daily.empty or len(spy_daily) < 200:
        raise RuntimeError(
            f"Insufficient SPY data for 200-DMA ({len(spy_daily)} rows, need 200)"
        )

    spy_price = float(spy_daily["Close"].iloc[-1])
    spy_sma_200 = float(spy_daily["Close"].rolling(200).mean().iloc[-1])

    regime = Regime.BULL if spy_price > spy_sma_200 else Regime.BEAR

    # VIXY: audit log only — real-time VIX proxy, does not gate trades
    vixy_price = data_client.fetch_vixy_price()

    logger.info(
        "Regime: %s | SPY=%.2f vs SMA200=%.2f | VIXY=%.2f (audit)",
        regime, spy_price, spy_sma_200, vixy_price,
    )
    return regime, vixy_price, spy_price, spy_sma_200
