"""
signals/indicators.py — Technical indicator calculations (v2).

v2 adds to v1's RSI + EMA:
  - MACD (Moving Average Convergence Divergence) — momentum
  - VWAP (Volume Weighted Average Price) — intraday fair value
  - Volume ratio — conviction filter
  - 5-day trend — medium-term direction

All indicators are computed from raw OHLCV data using pandas.
No external TA library — just math.

Why these indicators?
  RSI   — tells you if a stock is oversold (potential bounce)
  EMA   — tells you if price momentum is turning up
  MACD  — stronger momentum signal than EMA alone (two EMAs compared)
  VWAP  — if price > VWAP, institutional buyers are active intraday
  Volume— high volume confirms the move is real, not a fake-out
  5-day — ensures we're not buying a multi-day downtrend
"""

import logging
from dataclasses import dataclass

import pandas as pd
import yfinance as yf

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
    """Wilder's RSI. See indicators.py v1 for explanation."""
    delta = closes.diff()
    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)
    avg_gain = gains.ewm(com=period - 1, adjust=False).mean()
    avg_loss = losses.ewm(com=period - 1, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _calc_ema(closes: pd.Series, period: int) -> pd.Series:
    return closes.ewm(span=period, adjust=False).mean()


def _calc_macd(closes: pd.Series):
    """
    MACD = EMA(12) - EMA(26)
    Signal line = EMA(9) of MACD
    Bullish cross: MACD crosses above signal line (momentum turning positive)

    Returns (macd_line Series, signal_line Series)
    """
    ema12 = _calc_ema(closes, 12)
    ema26 = _calc_ema(closes, 26)
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    return macd_line, signal_line


def _calc_vwap(df: pd.DataFrame) -> pd.Series:
    """
    Intraday VWAP (Volume Weighted Average Price).
    VWAP = cumulative sum of (typical_price * volume) / cumulative volume
    Typical price = (High + Low + Close) / 3

    VWAP resets every day. We only use today's bars, so the cumsum
    naturally starts from the first bar of the day.

    Why VWAP matters:
      Institutions use VWAP as their benchmark — they try to buy below it.
      If price is ABOVE VWAP, it means buyers are driving price higher than
      the fair average for the day. That's a bullish intraday signal.
    """
    # Handle MultiIndex columns from yfinance
    high = df["High"] if "High" in df.columns else df[("High", df.columns.get_level_values(1)[0])]
    low = df["Low"] if "Low" in df.columns else df[("Low", df.columns.get_level_values(1)[0])]
    close = df["Close"] if "Close" in df.columns else df[("Close", df.columns.get_level_values(1)[0])]
    volume = df["Volume"] if "Volume" in df.columns else df[("Volume", df.columns.get_level_values(1)[0])]

    typical_price = (high + low + close) / 3
    vwap = (typical_price * volume).cumsum() / volume.cumsum()
    return vwap


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def fetch_indicators(
    ticker: str,
    rsi_period: int = 14,
    ema_fast: int = 9,
    ema_slow: int = 21,
) -> IndicatorSnapshot | None:
    """
    Download intraday bars and compute all indicators for the conviction scorer.

    We fetch two datasets:
      1. 5-minute bars (5d lookback) — for RSI, EMA, MACD, VWAP, volume
      2. Daily bars (15d lookback)   — for 5-day trend check

    Returns None if data is unavailable (market closed, bad ticker, API error).
    """
    try:
        # --- Intraday bars (5m, 5 days) ---
        df = yf.download(ticker, period="5d", interval="5m", progress=False)

        if df.empty or len(df) < 30:
            logger.warning("Not enough intraday data for %s", ticker)
            return None

        # Flatten MultiIndex columns (yfinance quirk)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        closes = df["Close"].dropna()
        volumes = df["Volume"].dropna()

        if len(closes) < 27:  # need at least 26 bars for EMA26
            return None

        # Calculate all series
        rsi_series = _calc_rsi(closes, rsi_period)
        ema_fast_s = _calc_ema(closes, ema_fast)
        ema_slow_s = _calc_ema(closes, ema_slow)
        ema_20_s = _calc_ema(closes, 20)
        macd_line_s, macd_signal_s = _calc_macd(closes)
        vwap_s = _calc_vwap(df)
        vol_avg = volumes.rolling(20).mean()

        # Today's bars only for VWAP (filter to today's date)
        today_str = pd.Timestamp.now(tz="America/New_York").date()
        today_mask = df.index.date == today_str
        if today_mask.sum() > 0:
            # Recompute VWAP for today's bars only so it resets at open
            today_df = df[today_mask]
            if isinstance(today_df.columns, pd.MultiIndex):
                today_df.columns = today_df.columns.get_level_values(0)
            vwap_today = _calc_vwap(today_df)
            current_vwap = float(vwap_today.iloc[-1])
        else:
            current_vwap = float(vwap_s.iloc[-1])

        # --- Daily bars (15d) for 5-day trend ---
        daily = yf.download(ticker, period="15d", interval="1d", progress=False)
        if isinstance(daily.columns, pd.MultiIndex):
            daily.columns = daily.columns.get_level_values(0)

        five_day_trend = False
        if len(daily) >= 6:
            five_day_trend = float(daily["Close"].iloc[-1]) > float(daily["Close"].iloc[-6])

        latest = closes.index[-1]
        prev_idx = -2

        return IndicatorSnapshot(
            ticker=ticker,
            price=float(closes.iloc[-1]),
            rsi=float(rsi_series.iloc[-1]),
            ema_fast=float(ema_fast_s.iloc[-1]),
            ema_slow=float(ema_slow_s.iloc[-1]),
            prev_ema_fast=float(ema_fast_s.iloc[prev_idx]),
            prev_ema_slow=float(ema_slow_s.iloc[prev_idx]),
            ema_20=float(ema_20_s.iloc[-1]),
            macd_line=float(macd_line_s.iloc[-1]),
            macd_signal=float(macd_signal_s.iloc[-1]),
            prev_macd_line=float(macd_line_s.iloc[prev_idx]),
            prev_macd_signal=float(macd_signal_s.iloc[prev_idx]),
            volume=float(volumes.iloc[-1]),
            volume_avg=float(vol_avg.iloc[-1]) if not pd.isna(vol_avg.iloc[-1]) else float(volumes.mean()),
            volume_ratio=float(volumes.iloc[-1] / vol_avg.iloc[-1]) if not pd.isna(vol_avg.iloc[-1]) else 1.0,
            vwap=current_vwap,
            five_day_trend=five_day_trend,
        )

    except Exception as exc:
        logger.error("Failed to fetch indicators for %s: %s", ticker, exc)
        return None


def ema_crossed_above(snap: IndicatorSnapshot) -> bool:
    """Fast EMA just crossed above slow EMA — bullish momentum."""
    return snap.prev_ema_fast < snap.prev_ema_slow and snap.ema_fast > snap.ema_slow


def macd_crossed_above(snap: IndicatorSnapshot) -> bool:
    """MACD line just crossed above signal line — stronger bullish momentum signal."""
    return snap.prev_macd_line < snap.prev_macd_signal and snap.macd_line > snap.macd_signal
