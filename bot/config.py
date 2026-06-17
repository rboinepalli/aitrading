"""
config.py — Single source of truth for all configuration.

Why centralise config here?
  - Every env var is validated at startup, not buried in individual modules.
  - If a key is missing, the bot fails loudly before placing any orders.
  - All magic numbers (thresholds, limits) live in one place — easy to tune.

TypeScript analogy: this is like a validated process.env file using Zod.
Python's `os.environ` is equivalent to Node's `process.env`.
"""

import os
from dataclasses import dataclass

# Load .env file when running locally.
# In Railway, env vars are set in the dashboard — dotenv is a no-op there.
from dotenv import load_dotenv
load_dotenv()


def _require(key: str) -> str:
    """Read an env var and raise clearly if it's missing."""
    value = os.environ.get(key)
    if not value:
        raise EnvironmentError(
            f"Missing required environment variable: {key}\n"
            f"See bot/.env.example for the full list."
        )
    return value


def _float(key: str, default: float) -> float:
    """Read a float env var with a fallback default."""
    return float(os.environ.get(key, default))


def _int(key: str, default: int) -> int:
    """Read an int env var with a fallback default."""
    return int(os.environ.get(key, default))


# ---------------------------------------------------------------------------
# Config dataclass
# ---------------------------------------------------------------------------
# A dataclass is like a TypeScript interface that also holds values.
# @dataclass auto-generates __init__, __repr__, etc. — no boilerplate needed.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)  # frozen=True means values can't be changed after creation
class Config:
    # Alpaca
    alpaca_api_key: str
    alpaca_secret_key: str
    alpaca_base_url: str

    # Supabase
    supabase_url: str
    supabase_service_key: str

    # Signal parameters
    rsi_period: int
    rsi_oversold: float
    rsi_overbought: float
    ema_fast: int
    ema_slow: int

    # Regime detection
    vix_bear_threshold: float   # VIX above this → BEAR
    vix_bull_threshold: float   # VIX below this (and above 200-DMA) → BULL

    # Risk management
    max_position_usd: float     # max dollars to spend per trade
    max_daily_loss_usd: float   # stop trading for the day if losses hit this
    take_profit_pct: float      # exit at this gain (0.15 = 15%)
    stop_loss_pct: float        # exit at this loss (0.10 = 10%)
    eod_close_time: str         # "HH:MM" in ET — hard close before market close

    # Tickers
    bull_ticker: str            # what to buy in a BULL regime
    bear_ticker: str            # what to buy in a BEAR regime


def load_config() -> Config:
    """
    Build and return the Config object from environment variables.
    Call this once at startup in main.py.
    """
    return Config(
        # Alpaca
        alpaca_api_key=_require("ALPACA_API_KEY"),
        alpaca_secret_key=_require("ALPACA_SECRET_KEY"),
        alpaca_base_url=os.environ.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets"),

        # Supabase
        supabase_url=_require("SUPABASE_URL"),
        supabase_service_key=_require("SUPABASE_SERVICE_KEY"),

        # Signals — all have sane defaults so you only override what you need
        rsi_period=_int("RSI_PERIOD", 14),
        rsi_oversold=_float("RSI_OVERSOLD", 30.0),
        rsi_overbought=_float("RSI_OVERBOUGHT", 70.0),
        ema_fast=_int("EMA_FAST", 9),
        ema_slow=_int("EMA_SLOW", 21),

        # Regime
        vix_bear_threshold=_float("VIX_BEAR_THRESHOLD", 25.0),
        vix_bull_threshold=_float("VIX_BULL_THRESHOLD", 18.0),

        # Risk
        max_position_usd=_float("MAX_POSITION_USD", 2000.0),
        max_daily_loss_usd=_float("MAX_DAILY_LOSS_USD", 500.0),
        take_profit_pct=_float("TAKE_PROFIT_PCT", 0.15),
        stop_loss_pct=_float("STOP_LOSS_PCT", 0.10),
        eod_close_time=os.environ.get("EOD_CLOSE_TIME", "15:45"),

        # Tickers
        bull_ticker=os.environ.get("BULL_TICKER", "TQQQ"),
        bear_ticker=os.environ.get("BEAR_TICKER", "SQQQ"),
    )
