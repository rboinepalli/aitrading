"""
data/market_data.py — Unified market data layer using Alpaca Data API.

All data comes from Alpaca (authenticated, IEX feed, no rate limits):
  - SPY daily bars    → 200-DMA for regime direction
  - Stock 5-min bars  → RSI, EMA, MACD, VWAP, volume for conviction scoring
  - VIXY latest bar   → VIX proxy, logged to Supabase for auditing only
                        (does NOT gate trades — conviction scoring handles quality)

Why not VIX as a gate?
  The CBOE CSV only has yesterday's VIX — stale for intraday decisions.
  VIXY (VIX futures ETF) is real-time but its price decays over time and
  doesn't map cleanly to VIX levels. More importantly, conviction scoring
  (5/8 signals: RSI, MACD, VWAP, volume...) already measures market quality
  directly on the ticker we want to trade — that's a better filter than VIX.

  Regime direction comes from SPY 200-DMA (BULL / BEAR).
  Trade quality comes from conviction score (must be ≥ 5 or 6).
  VIXY is logged alongside every signal for post-trade audit only.
"""

import logging
from datetime import datetime, timezone, timedelta

import pandas as pd
from alpaca.data.enums import DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, StockLatestBarRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

logger = logging.getLogger(__name__)

# Alpaca column names → Title Case we use everywhere in indicator math
_COL_MAP = {
    "open": "Open", "high": "High", "low": "Low",
    "close": "Close", "volume": "Volume",
}


def _normalise(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """
    Flatten Alpaca's MultiIndex DataFrame and standardise column names.

    Alpaca returns (symbol, timestamp) MultiIndex — we drop the symbol
    level and rename lowercase columns to Title Case (Open/High/Low/...).
    """
    if df is None or df.empty:
        return pd.DataFrame()
    # Drop symbol level from MultiIndex (present when fetching a single ticker)
    if isinstance(df.index, pd.MultiIndex):
        try:
            df = df.xs(ticker, level="symbol")
        except KeyError:
            df = df.droplevel(0)
    # Rename lowercase → Title Case; keep only OHLCV
    df = df.rename(columns=_COL_MAP)
    keep = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df.columns]
    return df[keep]


class MarketDataClient:
    """
    Fetches market data from Alpaca (stocks) and CBOE (VIX).

    One instance lives in main.py for the bot's lifetime — the connection
    is reused across all ticks rather than reconnecting every 5 minutes.
    """

    def __init__(self, api_key: str, secret_key: str):
        # StockHistoricalDataClient: Alpaca SDK class for historical bar data.
        # Uses the same API key as the trading client — no extra setup needed.
        self._client = StockHistoricalDataClient(
            api_key=api_key,
            secret_key=secret_key,
        )
        logger.info("MarketDataClient (Alpaca IEX) initialised")

    # -----------------------------------------------------------------------
    # VIXY — real-time VIX proxy for audit logging (does NOT gate trades)
    # -----------------------------------------------------------------------

    def fetch_vixy_price(self) -> float:
        """
        Fetch the latest VIXY bar close from Alpaca IEX.

        VIXY is a VIX short-term futures ETF — its price moves directionally
        with VIX (up when fear rises, down when calm). We log it alongside
        every signal for post-trade analysis so we can review what the fear
        environment looked like when each trade was taken.

        This does NOT gate any trades. Regime direction comes from SPY 200-DMA.
        Trade quality comes from conviction scoring. VIXY is audit data only.

        Returns 0.0 on failure — logged as-is, never blocks execution.
        """
        try:
            bars = self._client.get_stock_latest_bar(
                StockLatestBarRequest(symbol_or_symbols="VIXY", feed=DataFeed.IEX)
            )
            price = float(bars["VIXY"].close)
            logger.info("VIXY (VIX proxy, audit only): %.2f", price)
            return price
        except Exception as exc:
            logger.warning("Could not fetch VIXY price: %s — logging 0", exc)
            return 0.0

    # -----------------------------------------------------------------------
    # Stock bars — Alpaca Data API
    # -----------------------------------------------------------------------

    def get_daily_bars(self, ticker: str, days: int = 260) -> pd.DataFrame:
        """
        Fetch daily OHLCV bars for the past `days` calendar days.
        Returns DataFrame indexed by timezone-aware UTC timestamps.

        Used for: SPY 200-DMA, 5-day trend check.
        """
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=days + 15)  # +15 buffer for weekends/holidays
        try:
            bars = self._client.get_stock_bars(StockBarsRequest(
                symbol_or_symbols=ticker,
                timeframe=TimeFrame.Day,
                start=start,
                end=end,
                feed=DataFeed.IEX,   # free tier — paper accounts use IEX, not SIP
            ))
            return _normalise(bars.df, ticker)
        except Exception as exc:
            logger.error("get_daily_bars(%s): %s", ticker, exc)
            return pd.DataFrame()

    def get_intraday_bars(self, ticker: str, days: int = 5) -> pd.DataFrame:
        """
        Fetch 5-minute intraday OHLCV bars for the past `days` trading days.
        Returns DataFrame indexed by timezone-aware UTC timestamps.

        Used for: RSI, EMA, MACD, VWAP, volume ratio.
        """
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=days + 3)  # +3 buffer for weekends
        try:
            bars = self._client.get_stock_bars(StockBarsRequest(
                symbol_or_symbols=ticker,
                timeframe=TimeFrame(5, TimeFrameUnit.Minute),
                start=start,
                end=end,
                feed=DataFeed.IEX,   # free tier
            ))
            return _normalise(bars.df, ticker)
        except Exception as exc:
            logger.error("get_intraday_bars(%s): %s", ticker, exc)
            return pd.DataFrame()
