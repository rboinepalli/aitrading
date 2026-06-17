"""
signals/entry.py — Entry signal generation.

Combines regime + technical indicators to decide: BUY or NONE.

Entry rules:
  BULL regime  → check TQQQ:
    - RSI < rsi_oversold (price dipped, potential bounce)
    - EMA fast just crossed ABOVE EMA slow (momentum turning up)
    - Both must be true → BUY TQQQ

  BEAR regime  → check SQQQ:
    - RSI > rsi_overbought on the UNDERLYING (or use SQQQ's own RSI inversely)
    - EMA fast just crossed BELOW EMA slow on SQQQ (momentum turning up for the bear ETF)
    - Both must be true → BUY SQQQ

  CHOPPY → NONE — don't trade in directionless markets

Why require BOTH RSI AND EMA crossover?
  Using two independent indicators reduces false signals.
  RSI alone generates too many "bounce" signals that fizzle.
  The EMA crossover confirms that momentum has actually shifted.
  Requiring both filters out a lot of noise. This is called signal confluence.
"""

import logging
from dataclasses import dataclass
from enum import Enum

from config import Config
from signals.indicators import fetch_indicators, ema_crossed_above, ema_crossed_below
from signals.regime import Regime

logger = logging.getLogger(__name__)


class Signal(str, Enum):
    """
    Entry signal values.
    TypeScript analogy: `type Signal = 'BUY' | 'NONE'`
    """
    BUY = "BUY"
    NONE = "NONE"


@dataclass
class EntrySignal:
    """Full signal result — includes the signal value and context for logging/storage."""
    signal: Signal
    ticker: str             # which ticker to buy (or evaluated)
    regime: Regime
    rsi: float
    ema_fast: float
    ema_slow: float
    vix: float
    price: float
    reason: str             # human-readable explanation of why we did/didn't signal


def evaluate_entry(regime: Regime, vix: float, cfg: Config) -> EntrySignal:
    """
    Evaluate whether to enter a trade given the current regime.

    Args:
        regime: Current market regime (BULL/BEAR/CHOPPY)
        vix:    Current VIX value (passed in to avoid a second fetch)
        cfg:    Bot configuration (thresholds, tickers)

    Returns:
        EntrySignal with signal=BUY or signal=NONE
    """
    # CHOPPY → always sit out
    if regime == Regime.CHOPPY:
        return EntrySignal(
            signal=Signal.NONE,
            ticker="N/A",
            regime=regime,
            rsi=0.0, ema_fast=0.0, ema_slow=0.0,
            vix=vix, price=0.0,
            reason="CHOPPY regime — no trades",
        )

    # Choose which ticker to evaluate based on regime
    ticker = cfg.bull_ticker if regime == Regime.BULL else cfg.bear_ticker

    # Fetch the latest RSI + EMA values for that ticker
    snap = fetch_indicators(
        ticker=ticker,
        rsi_period=cfg.rsi_period,
        ema_fast=cfg.ema_fast,
        ema_slow=cfg.ema_slow,
    )

    if snap is None:
        return EntrySignal(
            signal=Signal.NONE,
            ticker=ticker,
            regime=regime,
            rsi=0.0, ema_fast=0.0, ema_slow=0.0,
            vix=vix, price=0.0,
            reason="Indicator fetch failed — skipping",
        )

    # -----------------------------------------------------------------------
    # BULL entry: RSI oversold + fast EMA crossed above slow EMA
    # -----------------------------------------------------------------------
    if regime == Regime.BULL:
        rsi_ok = snap.rsi < cfg.rsi_oversold
        crossover_ok = ema_crossed_above(snap)

        if rsi_ok and crossover_ok:
            reason = f"RSI={snap.rsi:.1f} < {cfg.rsi_oversold} AND EMA crossover up"
            return _buy_signal(snap, regime, vix, reason)
        else:
            parts = []
            if not rsi_ok:
                parts.append(f"RSI={snap.rsi:.1f} not oversold (<{cfg.rsi_oversold})")
            if not crossover_ok:
                parts.append("no EMA crossover")
            return _no_signal(snap, regime, vix, " | ".join(parts))

    # -----------------------------------------------------------------------
    # BEAR entry: fast EMA crossed below slow EMA on SQQQ
    # (SQQQ goes UP when the market goes DOWN, so EMA crossover logic is the
    # same as for a bull ETF — we want SQQQ's own upward momentum)
    # -----------------------------------------------------------------------
    if regime == Regime.BEAR:
        crossover_ok = ema_crossed_above(snap)   # SQQQ trending up

        if crossover_ok:
            reason = f"BEAR regime EMA crossover up on {ticker}"
            return _buy_signal(snap, regime, vix, reason)
        else:
            return _no_signal(snap, regime, vix, "no EMA crossover on SQQQ")

    # Fallback (shouldn't reach here)
    return _no_signal(snap, regime, vix, "unhandled regime")


# ---------------------------------------------------------------------------
# Private helpers — named with leading _ by Python convention (like private in TS)
# ---------------------------------------------------------------------------

def _buy_signal(snap, regime, vix, reason) -> EntrySignal:
    logger.info("BUY SIGNAL — %s | %s", snap.ticker, reason)
    return EntrySignal(
        signal=Signal.BUY,
        ticker=snap.ticker,
        regime=regime,
        rsi=snap.rsi,
        ema_fast=snap.ema_fast,
        ema_slow=snap.ema_slow,
        vix=vix,
        price=snap.price,
        reason=reason,
    )


def _no_signal(snap, regime, vix, reason) -> EntrySignal:
    logger.debug("No signal — %s | %s", snap.ticker, reason)
    return EntrySignal(
        signal=Signal.NONE,
        ticker=snap.ticker,
        regime=regime,
        rsi=snap.rsi,
        ema_fast=snap.ema_fast,
        ema_slow=snap.ema_slow,
        vix=vix,
        price=snap.price,
        reason=reason,
    )
