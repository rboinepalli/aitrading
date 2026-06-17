"""
config.py — Single source of truth for all configuration.

v2 adds:
  - Two strategy configs (A = aggressive_3x, B = conservative_multi)
  - Conviction scoring thresholds
  - Time window definitions (primary / dead zone / power hour)
  - Partial exit parameters
"""

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv
load_dotenv()


def _require(key: str) -> str:
    value = os.environ.get(key)
    if not value:
        raise EnvironmentError(f"Missing required env var: {key}\nSee bot/.env.example")
    return value


def _float(key: str, default: float) -> float:
    return float(os.environ.get(key, default))


def _int(key: str, default: int) -> int:
    return int(os.environ.get(key, default))


# ---------------------------------------------------------------------------
# StrategyConfig — describes one trading strategy
# TypeScript analogy: interface StrategyConfig { ... }
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class StrategyConfig:
    name: str                   # "aggressive_3x" or "conservative_multi"
    budget_usd: float           # max total capital deployed at once
    tickers: list               # which tickers this strategy can trade
    take_profit_pct: float      # close ALL shares at this gain
    partial_exit_pct: float     # sell HALF shares at this gain, move stop to breakeven
    stop_loss_pct: float        # close all at this loss
    primary_min_score: int      # min conviction score for 9:30–11am window
    power_hour_min_score: int   # min conviction score for 2pm–3:30pm window
    max_hold_days: int          # time stop — close after this many days
    regime_filter: list         # which regimes this strategy trades in


# ---------------------------------------------------------------------------
# Config — top-level bot configuration
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Config:
    # Alpaca
    alpaca_api_key: str
    alpaca_secret_key: str
    alpaca_base_url: str

    # Supabase
    supabase_url: str
    supabase_service_key: str

    # Shared risk
    max_per_trade_usd: float    # max $ for any single trade across both strategies
    max_daily_loss_usd: float   # per-strategy daily loss limit

    # Time windows (ET, "HH:MM")
    entry_window_start: str     # "09:30" — first valid entry
    entry_window_end: str       # "11:00" — end of primary window
    dead_zone_start: str        # "11:00"
    dead_zone_end: str          # "14:00"
    power_hour_start: str       # "14:00"
    power_hour_entry_cutoff: str# "15:30" — last entry in power hour
    force_close_time: str       # "15:45" — hard close all positions

    # RSI params (shared)
    rsi_period: int
    rsi_oversold: float         # threshold for RSI signal (< this = oversold)

    # Volume conviction threshold
    volume_ratio_threshold: float  # e.g. 1.5 = volume must be 1.5x the 20-bar avg

    # Strategy configs
    strategy_a: StrategyConfig
    strategy_b: StrategyConfig


def load_config() -> Config:
    """Build and return Config from environment variables. Called once at startup."""

    strategy_a = StrategyConfig(
        name="aggressive_3x",
        budget_usd=_float("STRATEGY_A_BUDGET", 10_000),
        # Tickers are regime-dependent for Strategy A; handled in strategy_a.py
        # We store both here; entry.py picks based on regime
        tickers=[
            os.environ.get("BULL_TICKER", "TQQQ"),
            os.environ.get("BEAR_TICKER", "SQQQ"),
        ],
        take_profit_pct=_float("A_TAKE_PROFIT_PCT", 0.15),
        partial_exit_pct=_float("A_PARTIAL_EXIT_PCT", 0.08),   # sell 50% at +8%
        stop_loss_pct=_float("A_STOP_LOSS_PCT", 0.10),
        primary_min_score=_int("A_PRIMARY_MIN_SCORE", 5),
        power_hour_min_score=_int("A_POWER_HOUR_MIN_SCORE", 6),
        max_hold_days=_int("A_MAX_HOLD_DAYS", 5),
        regime_filter=["BULL", "BEAR"],  # trades both directions
    )

    strategy_b = StrategyConfig(
        name="conservative_multi",
        budget_usd=_float("STRATEGY_B_BUDGET", 10_000),
        tickers=["QQQ", "NVDA", "AAPL", "MSFT", "AMD", "SPY"],
        take_profit_pct=_float("B_TAKE_PROFIT_PCT", 0.05),
        partial_exit_pct=_float("B_PARTIAL_EXIT_PCT", 0.03),   # sell 50% at +3%
        stop_loss_pct=_float("B_STOP_LOSS_PCT", 0.03),
        primary_min_score=_int("B_PRIMARY_MIN_SCORE", 5),
        power_hour_min_score=_int("B_POWER_HOUR_MIN_SCORE", 6),
        max_hold_days=_int("B_MAX_HOLD_DAYS", 5),
        regime_filter=["BULL"],          # BULL only — sits out BEAR and CHOPPY
    )

    return Config(
        alpaca_api_key=_require("ALPACA_API_KEY"),
        alpaca_secret_key=_require("ALPACA_SECRET_KEY"),
        alpaca_base_url=os.environ.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets"),

        supabase_url=_require("SUPABASE_URL"),
        supabase_service_key=_require("SUPABASE_SERVICE_KEY"),

        max_per_trade_usd=_float("MAX_PER_TRADE_USD", 2_000),
        max_daily_loss_usd=_float("MAX_DAILY_LOSS_USD", 500),

        # Time windows
        entry_window_start=os.environ.get("ENTRY_WINDOW_START", "09:30"),
        entry_window_end=os.environ.get("ENTRY_WINDOW_END", "11:00"),
        dead_zone_start=os.environ.get("DEAD_ZONE_START", "11:00"),
        dead_zone_end=os.environ.get("DEAD_ZONE_END", "14:00"),
        power_hour_start=os.environ.get("POWER_HOUR_START", "14:00"),
        power_hour_entry_cutoff=os.environ.get("POWER_HOUR_ENTRY_CUTOFF", "15:30"),
        force_close_time=os.environ.get("FORCE_CLOSE_TIME", "15:45"),

        rsi_period=_int("RSI_PERIOD", 14),
        rsi_oversold=_float("RSI_OVERSOLD", 35.0),   # tightened from 30 → 35

        volume_ratio_threshold=_float("VOLUME_RATIO_THRESHOLD", 1.5),

        strategy_a=strategy_a,
        strategy_b=strategy_b,
    )
