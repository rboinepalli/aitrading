"""
signals/regime.py — Market regime detection.

Data sources (v3 — no yfinance):
  VIX  → CBOE public CSV via MarketDataClient.fetch_vix()
          Real VIX values, cached for the trading day.
  SPY  → Alpaca Data API via MarketDataClient.get_daily_bars()

Regime rules:
  VIX > 25                       → BEAR  (high fear, likely downtrend)
  VIX < 18 AND SPY > 200-DMA    → BULL  (calm market, uptrend confirmed)
  anything else                  → CHOPPY (sit out)

Why 200-DMA?
  The 200-day SMA is the most widely watched trend filter in institutional
  trading. Price above it = healthy uptrend. Below it = risk-off territory.
"""

import logging
from enum import Enum

from data.market_data import MarketDataClient

logger = logging.getLogger(__name__)


class Regime(str, Enum):
    """
    Market regime enum.
    `str, Enum` means Regime.BULL == "BULL" — stores cleanly in Supabase.
    TypeScript analogy: type Regime = 'BULL' | 'BEAR' | 'CHOPPY'
    """
    BULL = "BULL"
    BEAR = "BEAR"
    CHOPPY = "CHOPPY"


def detect_regime(
    vix_bear_threshold: float,
    vix_bull_threshold: float,
    data_client: MarketDataClient,
) -> tuple[Regime, float, float, float]:
    """
    Determine the current market regime.

    Args:
        vix_bear_threshold: VIX above this → BEAR (default 25)
        vix_bull_threshold: VIX below this → consider BULL (default 18)
        data_client:        shared MarketDataClient (Alpaca + CBOE)

    Returns:
        (regime, vix, spy_price, spy_sma_200)

    Raises:
        RuntimeError if SPY data is unavailable (transient — next tick retries).
    """
    # VIX: cached CBOE CSV value — real VIX, fetched once per day
    vix = data_client.fetch_vix()

    # SPY: 260 days of daily bars for 200-DMA calculation
    # 200 trading days ≈ 290 calendar days. Request 320 to absorb holidays + weekends.
    spy_daily = data_client.get_daily_bars("SPY", days=320)
    if spy_daily.empty or len(spy_daily) < 200:
        raise RuntimeError(
            f"Insufficient SPY data for 200-DMA ({len(spy_daily)} rows, need 200)"
        )

    spy_price = float(spy_daily["Close"].iloc[-1])
    spy_sma_200 = float(spy_daily["Close"].rolling(200).mean().iloc[-1])

    # Apply regime rules in priority order
    if vix > vix_bear_threshold:
        regime = Regime.BEAR
    elif vix < vix_bull_threshold and spy_price > spy_sma_200:
        regime = Regime.BULL
    else:
        regime = Regime.CHOPPY

    logger.info(
        "Regime: %s | VIX=%.2f | SPY=%.2f vs SMA200=%.2f",
        regime, vix, spy_price, spy_sma_200,
    )
    return regime, vix, spy_price, spy_sma_200
