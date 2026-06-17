"""
signals/indicators.py — RSI + EMA calculated directly with pandas.

We removed pandas-ta (broken PyPI release) and compute the indicators
from scratch. This is actually better for learning — you see the real math.

RSI formula:
  1. Calculate daily price changes (diff)
  2. Separate gains and losses
  3. Compute average gain / average loss over N periods
  4. RS = avg_gain / avg_loss
  5. RSI = 100 - (100 / (1 + RS))

EMA formula:
  EMA uses an exponential weighting factor (alpha = 2 / (period + 1)).
  Each new EMA = alpha * current_price + (1 - alpha) * previous_EMA
  pandas' .ewm(span=N) does this in one call.

TypeScript analogy: these are pure functions — same input always gives same output.
"""

import logging
from dataclasses import dataclass

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


@dataclass
class IndicatorSnapshot:
    """The latest indicator values for a single ticker."""
    ticker: str
    rsi: float
    ema_fast: float         # fast EMA (e.g. 9-period)
    ema_slow: float         # slow EMA (e.g. 21-period)
    price: float            # latest close price
    prev_ema_fast: float    # previous candle's fast EMA (for crossover detection)
    prev_ema_slow: float    # previous candle's slow EMA


def _calc_rsi(closes: pd.Series, period: int) -> pd.Series:
    """
    Calculate RSI for a price series.

    closes: pandas Series of closing prices
    period: lookback window (standard is 14)
    """
    delta = closes.diff()                          # price change each candle

    # Separate gains (positive moves) from losses (negative moves)
    # .clip(lower=0) zeroes out negatives; .clip(upper=0) zeroes out positives
    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)                  # make losses positive

    # Rolling average — ewm gives Wilder's smoothing (standard for RSI)
    # adjust=False means it uses the recursive formula, not the window formula
    avg_gain = gains.ewm(com=period - 1, adjust=False).mean()
    avg_loss = losses.ewm(com=period - 1, adjust=False).mean()

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def _calc_ema(closes: pd.Series, period: int) -> pd.Series:
    """
    Calculate EMA for a price series.

    .ewm(span=N) is pandas' built-in exponential moving average.
    span=N corresponds to the standard EMA with alpha = 2/(N+1).
    adjust=False uses the recursive/streaming formula (not the window formula).
    """
    return closes.ewm(span=period, adjust=False).mean()


def fetch_indicators(
    ticker: str,
    rsi_period: int,
    ema_fast: int,
    ema_slow: int,
    interval: str = "5m",
    lookback: str = "5d",
) -> IndicatorSnapshot | None:
    """
    Download recent bars for `ticker` and return the latest RSI + EMA values.
    Returns None if data is unavailable.

    Args:
        ticker:     Stock symbol, e.g. "TQQQ"
        rsi_period: Lookback for RSI (default 14)
        ema_fast:   Fast EMA period (default 9)
        ema_slow:   Slow EMA period (default 21)
        interval:   Bar size — "5m" matches our polling interval
        lookback:   How far back to fetch — "5d" = ~390 five-minute bars
    """
    try:
        df = yf.download(ticker, period=lookback, interval=interval, progress=False)

        if df.empty or len(df) < max(rsi_period, ema_slow) + 5:
            logger.warning("Not enough data for %s (%d rows)", ticker, len(df))
            return None

        # yfinance can return a MultiIndex column when auto_adjust=True
        # Flatten it if so: ("Close", "TQQQ") → "Close"
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        closes = df["Close"].dropna()

        rsi_series = _calc_rsi(closes, rsi_period)
        ema_fast_series = _calc_ema(closes, ema_fast)
        ema_slow_series = _calc_ema(closes, ema_slow)

        # Need at least 2 rows to detect a crossover (current + previous)
        if len(closes) < 2:
            return None

        return IndicatorSnapshot(
            ticker=ticker,
            rsi=float(rsi_series.iloc[-1]),
            ema_fast=float(ema_fast_series.iloc[-1]),
            ema_slow=float(ema_slow_series.iloc[-1]),
            price=float(closes.iloc[-1]),
            prev_ema_fast=float(ema_fast_series.iloc[-2]),
            prev_ema_slow=float(ema_slow_series.iloc[-2]),
        )

    except Exception as exc:
        logger.error("Failed to fetch indicators for %s: %s", ticker, exc)
        return None


def ema_crossed_above(snap: IndicatorSnapshot) -> bool:
    """
    True if fast EMA just crossed ABOVE slow EMA — bullish momentum signal.
    Previous candle: fast < slow. Current candle: fast > slow.
    """
    was_below = snap.prev_ema_fast < snap.prev_ema_slow
    is_above = snap.ema_fast > snap.ema_slow
    return was_below and is_above


def ema_crossed_below(snap: IndicatorSnapshot) -> bool:
    """
    True if fast EMA just crossed BELOW slow EMA — bearish momentum signal.
    """
    was_above = snap.prev_ema_fast > snap.prev_ema_slow
    is_below = snap.ema_fast < snap.ema_slow
    return was_above and is_below
