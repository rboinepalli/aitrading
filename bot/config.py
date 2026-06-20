"""
config.py — Single source of truth for all configuration.

v3 adds:
  - Three strategy configs (A = aggressive_3x, B = momentum_stocks, C = aggressive_semis)
  - trailing_stop_pct: after partial exit, stop trails price instead of locking at breakeven
  - Dead zone narrowed to 11:30am–1:30pm (was 11am–2pm)
  - Strategy B upgraded to higher-volatility tickers (TSLA, META, COIN replace SPY/QQQ)
  - Strategy C: SOXL/SOXS (3x semiconductors), highest risk/reward
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
    name: str                   # "aggressive_3x", "momentum_stocks", "aggressive_semis"
    budget_usd: float           # max total capital deployed at once
    tickers: list               # which tickers this strategy can trade
    take_profit_pct: float      # close ALL shares at this gain
    partial_exit_pct: float     # sell HALF shares at this gain
    stop_loss_pct: float        # close all at this loss
    trailing_stop_pct: float    # after partial exit, trail stop this far below peak price
    primary_min_score: int      # min conviction score for primary window (default 5)
    power_hour_min_score: int   # min conviction score for power hour (default 6)
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
    max_per_trade_usd: float    # max $ for any single trade across all strategies
    max_daily_loss_usd: float   # per-strategy daily loss limit

    # Time windows (ET, "HH:MM")
    entry_window_start: str     # "09:30" — first valid entry
    entry_window_end: str       # "11:30" — end of primary window (also = dead zone start)
    dead_zone_start: str        # "11:30"
    dead_zone_end: str          # "13:30" — end of dead zone (also = power hour start)
    power_hour_start: str       # "13:30"
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
    strategy_c: StrategyConfig


def load_config() -> Config:
    """Build and return Config from environment variables. Called once at startup."""

    strategy_a = StrategyConfig(
        name="aggressive_3x",
        budget_usd=_float("STRATEGY_A_BUDGET", 10_000),
        # BULL regime → TQQQ (3x Nasdaq bull), BEAR regime → SQQQ (3x Nasdaq bear)
        tickers=[
            os.environ.get("BULL_TICKER", "TQQQ"),
            os.environ.get("BEAR_TICKER", "SQQQ"),
        ],
        take_profit_pct=_float("A_TAKE_PROFIT_PCT", 0.18),       # raised from 0.15
        partial_exit_pct=_float("A_PARTIAL_EXIT_PCT", 0.10),     # raised from 0.08
        stop_loss_pct=_float("A_STOP_LOSS_PCT", 0.09),           # tightened from 0.10
        trailing_stop_pct=_float("A_TRAILING_STOP_PCT", 0.05),   # 5% trail after partial
        primary_min_score=_int("A_PRIMARY_MIN_SCORE", 5),
        power_hour_min_score=_int("A_POWER_HOUR_MIN_SCORE", 6),
        max_hold_days=_int("A_MAX_HOLD_DAYS", 1),                # EOD only for leveraged
        regime_filter=["BULL", "BEAR"],  # trades both directions
    )

    strategy_b = StrategyConfig(
        name="momentum_stocks",
        budget_usd=_float("STRATEGY_B_BUDGET", 10_000),
        # High-volume, high-beta momentum stocks — bigger intraday moves than QQQ/SPY
        tickers=["NVDA", "AAPL", "MSFT", "AMD", "TSLA", "META", "COIN"],
        take_profit_pct=_float("B_TAKE_PROFIT_PCT", 0.08),       # raised from 0.05
        partial_exit_pct=_float("B_PARTIAL_EXIT_PCT", 0.04),     # raised from 0.03
        stop_loss_pct=_float("B_STOP_LOSS_PCT", 0.04),           # raised from 0.03
        trailing_stop_pct=_float("B_TRAILING_STOP_PCT", 0.025),  # 2.5% trail after partial
        primary_min_score=_int("B_PRIMARY_MIN_SCORE", 5),
        power_hour_min_score=_int("B_POWER_HOUR_MIN_SCORE", 6),
        max_hold_days=_int("B_MAX_HOLD_DAYS", 5),
        regime_filter=["BULL"],  # long only — BEAR/CHOPPY sits out
    )

    strategy_c = StrategyConfig(
        name="aggressive_semis",
        budget_usd=_float("STRATEGY_C_BUDGET", 5_000),           # smaller budget — highest volatility
        # BULL → SOXL (3x Semiconductors bull), BEAR → SOXS (3x bear)
        # Semis lead the Nasdaq — when NVDA/AMD/INTC move, SOXL amplifies 3x
        tickers=[
            os.environ.get("SEMIS_BULL_TICKER", "SOXL"),
            os.environ.get("SEMIS_BEAR_TICKER", "SOXS"),
        ],
        take_profit_pct=_float("C_TAKE_PROFIT_PCT", 0.20),       # 3x ETF needs room to run
        partial_exit_pct=_float("C_PARTIAL_EXIT_PCT", 0.11),
        stop_loss_pct=_float("C_STOP_LOSS_PCT", 0.12),
        trailing_stop_pct=_float("C_TRAILING_STOP_PCT", 0.06),   # 6% trail — more volatile
        primary_min_score=_int("C_PRIMARY_MIN_SCORE", 6),        # always 6 — no entry on weak signals
        power_hour_min_score=_int("C_POWER_HOUR_MIN_SCORE", 6),
        max_hold_days=_int("C_MAX_HOLD_DAYS", 1),                # EOD only for 3x leveraged
        regime_filter=["BULL", "BEAR"],
    )

    return Config(
        alpaca_api_key=_require("ALPACA_API_KEY"),
        alpaca_secret_key=_require("ALPACA_SECRET_KEY"),
        alpaca_base_url=os.environ.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets"),

        supabase_url=_require("SUPABASE_URL"),
        supabase_service_key=_require("SUPABASE_SERVICE_KEY"),

        max_per_trade_usd=_float("MAX_PER_TRADE_USD", 2_000),
        max_daily_loss_usd=_float("MAX_DAILY_LOSS_USD", 500),

        # Dead zone narrowed: 11:30am–1:30pm (was 11am–2pm)
        # This adds 1 extra hour of trading at both ends
        entry_window_start=os.environ.get("ENTRY_WINDOW_START", "09:30"),
        entry_window_end=os.environ.get("ENTRY_WINDOW_END", "11:30"),
        dead_zone_start=os.environ.get("DEAD_ZONE_START", "11:30"),
        dead_zone_end=os.environ.get("DEAD_ZONE_END", "13:30"),
        power_hour_start=os.environ.get("POWER_HOUR_START", "13:30"),
        power_hour_entry_cutoff=os.environ.get("POWER_HOUR_ENTRY_CUTOFF", "15:30"),
        force_close_time=os.environ.get("FORCE_CLOSE_TIME", "15:45"),

        rsi_period=_int("RSI_PERIOD", 14),
        rsi_oversold=_float("RSI_OVERSOLD", 35.0),

        volume_ratio_threshold=_float("VOLUME_RATIO_THRESHOLD", 1.5),

        strategy_a=strategy_a,
        strategy_b=strategy_b,
        strategy_c=strategy_c,
    )
