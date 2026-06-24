"""
alpaca_client.py — Alpaca SDK wrapper: quotes, historical bars, order placement.

Uses alpaca-py (newer SDK). All historical data via IEX feed (free tier).
"""
import logging
import math
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from typing import Optional

import pandas as pd
from alpaca.data import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, StockLatestQuoteRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.data.enums import DataFeed
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

from config import ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_BASE_URL, PHASE

logger = logging.getLogger(__name__)

_paper = "paper-api" in ALPACA_BASE_URL
_hist  = StockHistoricalDataClient(ALPACA_API_KEY, ALPACA_SECRET_KEY)
_trade = TradingClient(ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=_paper)


@dataclass
class Quote:
    ticker: str
    price: float
    tradable: bool


def get_quote(ticker: str) -> Optional[Quote]:
    """Fetch latest real-time quote for a ticker."""
    try:
        req  = StockLatestQuoteRequest(symbol_or_symbols=ticker, feed=DataFeed.IEX)
        data = _hist.get_stock_latest_quote(req)
        q    = data[ticker]
        mid  = (q.ask_price + q.bid_price) / 2 if q.ask_price and q.bid_price else q.ask_price or q.bid_price
        return Quote(ticker=ticker, price=float(mid or 0), tradable=True)
    except Exception as e:
        logger.warning("get_quote(%s): %s", ticker, e)
        return None


def get_daily_bars(ticker: str, limit: int = 60) -> Optional[pd.DataFrame]:
    """
    Fetch daily OHLCV bars. Returns a clean DataFrame with columns:
    Open, High, Low, Close, Volume — indexed by date.
    """
    try:
        end   = datetime.now(timezone.utc)
        start = end - timedelta(days=limit * 2)   # * 2 for weekends/holidays
        req   = StockBarsRequest(
            symbol_or_symbols=ticker,
            timeframe=TimeFrame.Day,
            start=start, end=end,
            feed=DataFeed.IEX,
            limit=limit,
        )
        bars = _hist.get_stock_bars(req)
        df   = bars.df
        if df.empty:
            return None
        # alpaca-py returns a MultiIndex (symbol, timestamp) — drop the symbol level
        if isinstance(df.index, pd.MultiIndex):
            df = df.xs(ticker, level=0)
        df.index = pd.to_datetime(df.index)
        df.columns = [c.title() for c in df.columns]
        return df.tail(limit)
    except Exception as e:
        logger.warning("get_daily_bars(%s): %s", ticker, e)
        return None


def get_intraday_bars(ticker: str, days: int = 1) -> Optional[pd.DataFrame]:
    """
    Fetch 1-minute intraday bars for today (used for VWAP calculation).
    """
    try:
        end   = datetime.now(timezone.utc)
        start = end - timedelta(days=days)
        req   = StockBarsRequest(
            symbol_or_symbols=ticker,
            timeframe=TimeFrame(1, TimeFrameUnit.Minute),
            start=start, end=end,
            feed=DataFeed.IEX,
        )
        bars = _hist.get_stock_bars(req)
        df   = bars.df
        if df.empty:
            return None
        if isinstance(df.index, pd.MultiIndex):
            df = df.xs(ticker, level=0)
        df.index = pd.to_datetime(df.index)
        df.columns = [c.title() for c in df.columns]
        return df
    except Exception as e:
        logger.warning("get_intraday_bars(%s): %s", ticker, e)
        return None


def calculate_shares(price: float, max_dollars: float) -> int:
    """Whole shares only. Never fractional."""
    if price <= 0:
        return 0
    return math.floor(max_dollars / price)


def buy(ticker: str, shares: int) -> Optional[str]:
    """Submit a market buy order. Returns order ID or None on error."""
    if PHASE == "paper":
        logger.info("[PAPER] BUY %d shares %s", shares, ticker)
    try:
        req   = MarketOrderRequest(
            symbol=ticker,
            qty=shares,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
        )
        order = _trade.submit_order(req)
        logger.info("BUY order submitted: %s x%d | id=%s", ticker, shares, order.id)
        return str(order.id)
    except Exception as e:
        logger.error("BUY %s x%d failed: %s", ticker, shares, e)
        return None


def sell(ticker: str, shares: int, reason: str = "") -> Optional[str]:
    """Submit a market sell order. Returns order ID or None on error."""
    if PHASE == "paper":
        logger.info("[PAPER] SELL %d shares %s reason=%s", shares, ticker, reason)
    try:
        req   = MarketOrderRequest(
            symbol=ticker,
            qty=shares,
            side=OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
        )
        order = _trade.submit_order(req)
        logger.info("SELL order submitted: %s x%d reason=%s | id=%s", ticker, shares, reason, order.id)
        return str(order.id)
    except Exception as e:
        logger.error("SELL %s x%d failed: %s", ticker, shares, e)
        return None


def get_buying_power() -> float:
    try:
        acct = _trade.get_account()
        return float(acct.buying_power)
    except Exception as e:
        logger.error("get_buying_power: %s", e)
        return 0.0


def get_open_position(ticker: str) -> Optional[dict]:
    """Return open position dict {shares, avg_entry, current_price, unrealized_pnl_pct} or None."""
    try:
        pos = _trade.get_open_position(ticker)
        return {
            "ticker":            ticker,
            "shares":            int(float(pos.qty)),
            "avg_entry":         float(pos.avg_entry_price),
            "current_price":     float(pos.current_price),
            "unrealized_pnl_pct": float(pos.unrealized_plpc) * 100,
        }
    except Exception:
        return None
