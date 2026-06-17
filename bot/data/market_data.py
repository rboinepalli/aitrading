"""
data/market_data.py — Unified market data layer.

Data sources:
  VIX    → CBOE public CSV (no auth, CDN, no rate limits)
             https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv
             Fetched once per day, cached in memory for all ticks.
             Gives the previous day's VIX close — stable for regime classification.

  Stocks → Alpaca Data API (authenticated, no IP-based rate limits)
             Same credentials as our trading account — no extra cost or setup.
             Replaces yfinance which rate-limits aggressively on cloud servers.

Why not yfinance?
  Yahoo Finance throttles requests from cloud IPs (Railway, AWS, GCP) far more
  aggressively than home IPs. The error YFRateLimitError appears on nearly every
  tick when deployed on shared hosting. Switching to authenticated sources
  eliminates this entirely.
"""

import logging
from datetime import datetime, timezone, timedelta, date
from typing import Optional

import pandas as pd
import requests
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

logger = logging.getLogger(__name__)

CBOE_VIX_CSV_URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"

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
        # VIX cache: fetched once per trading day, reused for all ticks.
        # TypeScript analogy: { date: string | null; value: number | null }
        self._vix_cache_date: Optional[date] = None
        self._vix_cache_value: Optional[float] = None
        logger.info("MarketDataClient (Alpaca + CBOE) initialised")

    # -----------------------------------------------------------------------
    # VIX — CBOE public CSV
    # -----------------------------------------------------------------------

    def fetch_vix(self) -> float:
        """
        Fetch the latest VIX close from CBOE's public VIX history CSV.

        The CSV contains daily historical VIX data, updated after each
        market session. The most recent row is the previous day's close —
        appropriate for a regime filter since VIX is a trend indicator, not
        a tick-by-tick signal.

        Caches the value for the entire trading day to avoid redundant
        HTTP requests (the underlying data doesn't change intraday).

        Falls back to 20.0 (CHOPPY territory) if the fetch fails.
        """
        today = datetime.now(timezone.utc).date()

        # Return cached value if already fetched today
        if self._vix_cache_date == today and self._vix_cache_value is not None:
            logger.debug("VIX from cache: %.2f", self._vix_cache_value)
            return self._vix_cache_value

        try:
            resp = requests.get(CBOE_VIX_CSV_URL, timeout=15)
            resp.raise_for_status()

            # CSV format: DATE,OPEN,HIGH,LOW,CLOSE
            # Example row: 06/16/2026,14.23,15.01,13.98,14.55
            lines = [ln.strip() for ln in resp.text.strip().split("\n") if ln.strip()]
            # Skip header row, take the last data row
            last_row = lines[-1].split(",")
            vix_close = float(last_row[4])  # CLOSE column index

            self._vix_cache_date = today
            self._vix_cache_value = vix_close
            logger.info("VIX from CBOE CSV: %.2f  (row date: %s)", vix_close, last_row[0])
            return vix_close

        except Exception as exc:
            logger.error("Failed to fetch VIX from CBOE: %s", exc)
            # If we have a stale cache from a previous day, still use it — better than nothing
            if self._vix_cache_value is not None:
                logger.warning("Using stale VIX cache: %.2f", self._vix_cache_value)
                return self._vix_cache_value
            # Conservative default: 20 puts us in CHOPPY (no trades) until real data arrives
            logger.warning("No VIX data available — defaulting to 20.0 (CHOPPY)")
            return 20.0

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
            ))
            return _normalise(bars.df, ticker)
        except Exception as exc:
            logger.error("get_intraday_bars(%s): %s", ticker, exc)
            return pd.DataFrame()
