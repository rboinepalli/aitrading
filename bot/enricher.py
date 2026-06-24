"""
enricher.py — Step 2: Fetch OHLCV + compute indicators via pandas-ta.

For each candidate ticker:
  - Daily bars (60 days) → EMA9, EMA20, RSI14, ATR14, volume ratio
  - Intraday bars (today, 1-min) → VWAP
  - Real-time quote → current price, confirm tradable
"""
import logging
from dataclasses import dataclass
from typing import Optional

import pandas as pd
import pandas_ta as ta

import alpaca_client as alpaca

logger = logging.getLogger(__name__)


@dataclass
class Indicators:
    ticker: str
    price: float          # real-time mid price
    change_pct: float     # % change from prev close
    rsi: float
    ema9: float
    ema20: float
    atr: float            # ATR(14) in dollars — used for stop/target sizing
    volume_ratio: float   # today's vol ÷ 10-day avg vol
    vwap: float
    # Derived booleans (computed from above)
    above_ema9: bool
    above_ema20: bool
    above_vwap: bool


def enrich(ticker: str) -> Optional[Indicators]:
    """
    Fetch all indicators for a single ticker.
    Returns None if data is unavailable or ticker is illiquid.
    """
    # --- Real-time quote ---
    quote = alpaca.get_quote(ticker)
    if not quote or quote.price <= 0:
        logger.warning("enrich(%s): no quote", ticker)
        return None

    price = quote.price

    # --- Daily bars for EMA, RSI, ATR, volume ratio ---
    daily = alpaca.get_daily_bars(ticker, limit=60)
    if daily is None or len(daily) < 20:
        logger.warning("enrich(%s): insufficient daily bars", ticker)
        return None

    # pandas-ta appends columns directly to the DataFrame
    daily.ta.ema(length=9,  append=True)
    daily.ta.ema(length=20, append=True)
    daily.ta.rsi(length=14, append=True)
    daily.ta.atr(length=14, append=True)

    last = daily.iloc[-1]

    ema9  = float(last.get("EMA_9",  last.get("ema_9",  0)) or 0)
    ema20 = float(last.get("EMA_20", last.get("ema_20", 0)) or 0)
    rsi   = float(last.get("RSI_14", last.get("rsi_14", 0)) or 50)
    atr   = float(last.get("ATRr_14", last.get("atrr_14", 0)) or last.get("ATR_14", 0) or 0)

    # Volume ratio: today's volume ÷ 10-day average
    vol_10d_avg  = float(daily["Volume"].tail(11).iloc[:-1].mean()) if len(daily) >= 11 else 1
    today_volume = float(last.get("Volume", 0) or 0)
    volume_ratio = (today_volume / vol_10d_avg) if vol_10d_avg > 0 else 1.0

    # % change from previous close
    prev_close  = float(daily["Close"].iloc[-2]) if len(daily) >= 2 else price
    change_pct  = ((price - prev_close) / prev_close * 100) if prev_close > 0 else 0

    # --- Intraday bars for VWAP ---
    vwap = price  # fallback
    intraday = alpaca.get_intraday_bars(ticker, days=1)
    if intraday is not None and len(intraday) >= 5:
        intraday.ta.vwap(append=True)
        vwap_col = [c for c in intraday.columns if "VWAP" in c.upper()]
        if vwap_col:
            v = intraday[vwap_col[0]].iloc[-1]
            if v and not pd.isna(v):
                vwap = float(v)

    return Indicators(
        ticker=ticker,
        price=price,
        change_pct=change_pct,
        rsi=rsi,
        ema9=ema9,
        ema20=ema20,
        atr=atr,
        volume_ratio=volume_ratio,
        vwap=vwap,
        above_ema9=price > ema9 if ema9 > 0 else False,
        above_ema20=price > ema20 if ema20 > 0 else False,
        above_vwap=price > vwap if vwap > 0 else False,
    )


def enrich_all(tickers: list[str]) -> list[Indicators]:
    """Enrich a list of tickers, skipping any that fail."""
    results = []
    for ticker in tickers:
        try:
            ind = enrich(ticker)
            if ind:
                results.append(ind)
                logger.debug("  enriched %s price=$%.2f rsi=%.1f vol=%.1fx",
                             ticker, ind.price, ind.rsi, ind.volume_ratio)
        except Exception as e:
            logger.warning("enrich_all(%s): %s", ticker, e)
    logger.info("Enriched %d/%d tickers", len(results), len(tickers))
    return results
