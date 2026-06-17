"""
signals/regime.py — Market regime detection.

We classify the current market as one of three regimes:
  BULL   → uptrend, low fear → trade leveraged bull ETF (TQQQ)
  BEAR   → downtrend, high fear → trade leveraged bear ETF (SQQQ)
  CHOPPY → no clear direction → sit out, no trades

How we detect regime:
  1. VIX (the "fear index") — when VIX is high, markets are volatile and risky
     - VIX > 25  → BEAR (fear is elevated, trend likely down)
     - VIX < 18  → potentially BULL (calm market)
  2. SPY 200-day SMA — the gold standard trend indicator
     - Price > 200-DMA → long-term uptrend (confirms BULL)
     - Price < 200-DMA → long-term downtrend
  3. Combined rule:
     - VIX > 25                       → BEAR
     - VIX < 18 AND price > 200-DMA  → BULL
     - anything else                  → CHOPPY

Why VIX?
  VIX is the CBOE Volatility Index. It measures expected 30-day volatility of the S&P 500
  derived from options pricing. High VIX = fear/uncertainty. Low VIX = complacency.
  It's a proxy for "how scared is the market right now."

Why 200-DMA?
  The 200-day moving average is the most widely watched trend filter.
  When price is above it, most institutional buyers consider the market healthy.
  The major indices (and TQQQ) tend to trend when price > 200-DMA.
"""

import logging
from enum import Enum
from typing import Optional

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


class Regime(str, Enum):
    """
    Market regime enum.

    `str, Enum` means each value is also a string — so Regime.BULL == "BULL".
    This makes it easy to store in Supabase without conversion.
    TypeScript analogy: `type Regime = 'BULL' | 'BEAR' | 'CHOPPY'`
    """
    BULL = "BULL"
    BEAR = "BEAR"
    CHOPPY = "CHOPPY"


def _extract_close(data: pd.DataFrame, ticker: str) -> Optional[pd.Series]:
    """
    Safely extract the Close column from a yfinance DataFrame.

    yfinance 0.2.x returns MultiIndex columns even for single tickers:
      ("Close", "^VIX"), ("Open", "^VIX"), ...
    So data["Close"] returns a DataFrame, not a Series.
    This helper handles both the old (flat) and new (MultiIndex) formats.
    """
    if data.empty:
        return None
    if isinstance(data.columns, pd.MultiIndex):
        # MultiIndex: ("Close", ticker) — squeeze to Series
        if ("Close", ticker) in data.columns:
            return data[("Close", ticker)]
        # Fallback: grab whatever is in the Close level
        try:
            return data["Close"].squeeze()
        except Exception:
            return None
    # Flat columns
    if "Close" in data.columns:
        return data["Close"]
    return None


def fetch_vix() -> Optional[float]:
    """
    Fetch the latest VIX value from Yahoo Finance.
    Returns None if the fetch fails (e.g. outside market hours).

    VIX ticker on Yahoo Finance is '^VIX'.
    """
    try:
        data = yf.download("^VIX", period="2d", interval="1d", progress=False)
        closes = _extract_close(data, "^VIX")
        if closes is None or closes.empty:
            logger.warning("VIX data empty or unavailable")
            return None
        return float(closes.iloc[-1])
    except Exception as exc:
        logger.error("Failed to fetch VIX: %s", exc)
        return None


def fetch_spy_vs_200dma() -> Optional[tuple[float, float]]:
    """
    Fetch SPY's latest price and its 200-day SMA.
    Returns (current_price, sma_200) or None on failure.

    We use SPY (not QQQ) because the 200-DMA on SPY is the most
    widely respected trend filter for US equities broadly.
    """
    try:
        # Fetch 250 trading days — enough for a 200-period SMA to be stable
        data = yf.download("SPY", period="250d", interval="1d", progress=False)
        closes = _extract_close(data, "SPY")
        if closes is None or len(closes) < 200:
            logger.warning("Not enough SPY data for 200-DMA (%d rows)", len(closes) if closes is not None else 0)
            return None

        current_price = float(closes.iloc[-1])

        # .rolling(200).mean() computes a 200-period rolling average.
        # TypeScript analogy: reduce + sliding window — pandas does it in one line.
        sma_200 = float(closes.rolling(200).mean().iloc[-1])

        return current_price, sma_200
    except Exception as exc:
        logger.error("Failed to fetch SPY 200-DMA: %s", exc)
        return None


def detect_regime(
    vix_bear_threshold: float,
    vix_bull_threshold: float,
) -> tuple[Regime, float, float, float]:
    """
    Determine the current market regime and return supporting data.

    Returns:
        (regime, vix, spy_price, spy_sma_200)

    Raises:
        RuntimeError if market data is unavailable.
    """
    vix = fetch_vix()
    spy_data = fetch_spy_vs_200dma()

    if vix is None or spy_data is None:
        # Fall back to CHOPPY so the loop keeps running — no trades happen but bot stays alive.
        # Root cause is usually a yfinance hiccup at market open; it self-heals next tick.
        logger.warning("Market data unavailable — defaulting regime to CHOPPY this tick")
        raise RuntimeError("Cannot determine regime: market data unavailable")

    spy_price, spy_sma_200 = spy_data

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
