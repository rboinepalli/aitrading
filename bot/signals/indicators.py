"""
signals/indicators.py — Technical indicator calculations (v3).

v3: switched from yfinance to Alpaca Data API (no cloud IP rate limits).

Computes from raw OHLCV data using pandas — no external TA library.

Indicators:
  RSI   — oversold bounce signal (< 35 = entry condition)
  EMA   — trend direction via fast/slow crossover
  MACD  — stronger momentum signal (two EMAs compared)
  VWAP  — intraday fair value; price > VWAP = institutions buying
  Volume— high volume confirms the move is real, not a fake-out
  5-day — medium-term trend (today > 5 trading days ago)
"""

import logging
from dataclasses import dataclass
from typing import Optional

import pandas as pd

from data.market_data import MarketDataClient

logger = logging.getLogger(__name__)


@dataclass
class IndicatorSnapshot:
    """All indicator values for a single ticker at a single point in time."""
    ticker: str
    price: float            # latest close

    # RSI
    rsi: float              # 0–100, < 35 = oversold signal

    # EMA (for trend direction)
    ema_fast: float         # 9-period
    ema_slow: float         # 21-period
    prev_ema_fast: float    # previous bar (crossover detection)
    prev_ema_slow: float

    # EMA20 (separate from crossover EMAs — used for trend confirmation)
    ema_20: float           # price > ema_20 = trend intact

    # MACD
    macd_line: float        # MACD line = EMA12 - EMA26
    macd_signal: float      # signal line = EMA9 of MACD line
    prev_macd_line: float   # previous bar (crossover detection)
    prev_macd_signal: float

    # Volume
    volume: float           # current bar volume
    volume_avg: float       # 20-bar average volume
    volume_ratio: float     # volume / volume_avg (> 1.5 = conviction)

    # VWAP (intraday, resets at market open)
    vwap: float             # price > vwap = intraday bullish

    # 5-day trend
    five_day_trend: bool    # True if today's close > close 5 trading days ago


# ---------------------------------------------------------------------------
# Private calculation helpers
# ---------------------------------------------------------------------------

def _calc_rsi(closes: pd.Series, period: int) -> pd.Series:
    """
    Wilder's RSI — measures how overbought/oversold a stock is.
    Range: 0–100. Below 35 = oversold (potential bounce).
    Uses exponential moving average (EWM) of gains vs losses.
    """
    delta = closes.diff()
    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)
    avg_gain = gains.ewm(com=period - 1, adjust=False).mean()
    avg_loss = losses.ewm(com=period - 1, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _calc_ema(closes: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average — gives more weight to recent prices."""
    return closes.ewm(span=period, adjust=False).mean()


def _calc_macd(closes: pd.Series):
    """
    MACD = EMA(12) - EMA(26)
    Signal line = EMA(9) of MACD
    Bullish cross: MACD crosses above signal line = momentum turning positive.
    Returns (macd_line Series, signal_line Series).
    """
    ema12 = _calc_ema(closes, 12)
    ema26 = _calc_ema(closes, 26)
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    return macd_line, signal_line


def _calc_vwap(df: pd.DataFrame) -> pd.Series:
    """
    Intraday VWAP (Volume Weighted Average Price).
    Formula: cumsum(typical_price × volume) / cumsum(volume)
    Typical price = (High + Low + Close) / 3

    VWAP resets every day. We filter to today's bars only before calling,
    so the cumsum naturally starts from the first bar of the day.

    Why VWAP matters:
      Institutions benchmark their execution to VWAP.
      Price above VWAP = buyers are in control intraday.
    """
    typical_price = (df["High"] + df["Low"] + df["Close"]) / 3
    vwap = (typical_price * df["Volume"]).cumsum() / df["Volume"].cumsum()
    return vwap


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def fetch_indicators(
    ticker: str,
    data_client: MarketDataClient,
    rsi_period: int = 14,
    ema_fast: int = 9,
    ema_slow: int = 21,
) -> Optional[IndicatorSnapshot]:
    """
    Fetch bars via Alpaca and compute all indicators for the conviction scorer.

    Two datasets:
      1. 5-minute bars (5d lookback) — RSI, EMA, MACD, VWAP, volume
      2. Daily bars (15d lookback)   — 5-day trend check

    Returns None if data is unavailable (market closed, bad ticker, API error).
    """
    try:
        # --- Intraday bars (5m) ---
        df = data_client.get_intraday_bars(ticker, days=5)

        if df.empty or len(df) < 30:
            logger.warning("Not enough intraday data for %s (%d rows)", ticker, len(df))
            return None

        closes = df["Close"].dropna()
        volumes = df["Volume"].dropna()

        if len(closes) < 27:  # need at least 26 bars for EMA26
            return None

        # Calculate all indicator series
        rsi_series    = _calc_rsi(closes, rsi_period)
        ema_fast_s    = _calc_ema(closes, ema_fast)
        ema_slow_s    = _calc_ema(closes, ema_slow)
        ema_20_s      = _calc_ema(closes, 20)
        macd_line_s, macd_signal_s = _calc_macd(closes)
        vol_avg       = volumes.rolling(20).mean()

        # VWAP for today's bars only (resets at market open).
        # Alpaca timestamps are UTC — convert to ET for date comparison.
        today_et = pd.Timestamp.now(tz="America/New_York").date()
        if df.index.tz is not None:
            bar_dates = df.index.tz_convert("America/New_York").date
        else:
            bar_dates = df.index.date

        today_mask = bar_dates == today_et
        if today_mask.sum() > 0:
            today_df = df[today_mask].copy()
            current_vwap = float(_calc_vwap(today_df).iloc[-1])
        else:
            # Fallback: use all bars (e.g., premarket run)
            current_vwap = float(_calc_vwap(df).iloc[-1])

        # --- Daily bars (15d) for 5-day trend ---
        daily = data_client.get_daily_bars(ticker, days=15)
        five_day_trend = False
        if not daily.empty and len(daily) >= 6:
            five_day_trend = float(daily["Close"].iloc[-1]) > float(daily["Close"].iloc[-6])

        # --- Assemble snapshot ---
        vol_avg_last = vol_avg.iloc[-1]
        vol_ratio = (
            float(volumes.iloc[-1] / vol_avg_last)
            if not pd.isna(vol_avg_last) and vol_avg_last > 0
            else 1.0
        )

        return IndicatorSnapshot(
            ticker=ticker,
            price=float(closes.iloc[-1]),
            rsi=float(rsi_series.iloc[-1]),
            ema_fast=float(ema_fast_s.iloc[-1]),
            ema_slow=float(ema_slow_s.iloc[-1]),
            prev_ema_fast=float(ema_fast_s.iloc[-2]),
            prev_ema_slow=float(ema_slow_s.iloc[-2]),
            ema_20=float(ema_20_s.iloc[-1]),
            macd_line=float(macd_line_s.iloc[-1]),
            macd_signal=float(macd_signal_s.iloc[-1]),
            prev_macd_line=float(macd_line_s.iloc[-2]),
            prev_macd_signal=float(macd_signal_s.iloc[-2]),
            volume=float(volumes.iloc[-1]),
            volume_avg=float(vol_avg_last) if not pd.isna(vol_avg_last) else float(volumes.mean()),
            volume_ratio=vol_ratio,
            vwap=current_vwap,
            five_day_trend=five_day_trend,
        )

    except Exception as exc:
        logger.error("Failed to compute indicators for %s: %s", ticker, exc)
        return None


def ema_crossed_above(snap: IndicatorSnapshot) -> bool:
    """Fast EMA just crossed above slow EMA — bullish momentum."""
    return snap.prev_ema_fast < snap.prev_ema_slow and snap.ema_fast > snap.ema_slow


def macd_crossed_above(snap: IndicatorSnapshot) -> bool:
    """MACD line just crossed above signal line — stronger bullish momentum signal."""
    return snap.prev_macd_line < snap.prev_macd_signal and snap.macd_line > snap.macd_signal
