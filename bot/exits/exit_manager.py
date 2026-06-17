"""
exits/exit_manager.py — Position exit logic with partial exits.

v2 adds PARTIAL EXIT logic:
  - Sell 50% of shares when gain hits the partial_exit_pct threshold
  - Move stop loss to breakeven (entry price) after partial exit
  - Let the remaining 50% run to the full take_profit_pct target

Example (Strategy A):
  Entry: 100 shares TQQQ @ $50 = $5,000
  At +8%: sell 50 shares @ $54 → locks in +$200 profit
          stop moves to $50 (breakeven on remaining 50 shares)
  At +15%: sell remaining 50 shares @ $57.50 → locks in +$375
  Total realized: +$575 instead of risking full position

  vs. simple exit at +15%:
  If price hits +8% then reverses to -5%, with partial exit you still
  made money. With no partial exit you'd lose $250.

ExitReason values:
  PARTIAL_PROFIT  → first partial exit (50% sold, trade stays open)
  TAKE_PROFIT     → full take profit (remaining 50% sold)
  STOP_LOSS       → full stop loss (all remaining sold)
  EOD_CLOSE       → forced close at 3:45pm
  NONE            → no exit triggered
"""

import logging
from dataclasses import dataclass
from datetime import datetime, time
from enum import Enum

import pytz

from broker.alpaca_client import OpenPosition
from config import Config, StrategyConfig

logger = logging.getLogger(__name__)
ET = pytz.timezone("America/New_York")


class ExitReason(str, Enum):
    PARTIAL_PROFIT = "PARTIAL_PROFIT"   # sold 50%, trade still open
    TAKE_PROFIT = "TAKE_PROFIT"         # sold remaining, trade closed
    STOP_LOSS = "STOP_LOSS"             # stop hit, trade closed
    EOD_CLOSE = "EOD_CLOSE"             # hard close at 3:45pm
    NONE = "NONE"


@dataclass
class ExitDecision:
    should_exit: bool       # True = execute a sell order
    exit_all: bool          # True = close full position; False = sell 50% (partial)
    reason: ExitReason
    detail: str


def check_exit(
    position: OpenPosition,
    strategy: StrategyConfig,
    partial_already_triggered: bool,
    stop_price: float | None,          # None = use strategy default; entry_price after partial
    force_close_time: str,
) -> ExitDecision:
    """
    Evaluate all exit conditions for an open position.

    Args:
        position:                  Current open position from Alpaca
        strategy:                  Strategy config (take_profit, stop_loss thresholds)
        partial_already_triggered: True if we already sold 50% earlier
        stop_price:                Dynamic stop (moves to breakeven after partial exit)
        force_close_time:          "HH:MM" hard close time (e.g. "15:45")

    Returns:
        ExitDecision
    """
    pnl_pct = position.unrealized_pnl_pct  # e.g. 0.08 = +8%

    # Determine effective stop — if partial exit already happened,
    # stop is at breakeven (entry_price). Otherwise use strategy's stop_loss_pct.
    if partial_already_triggered and stop_price is not None:
        effective_stop = (stop_price - position.entry_price) / position.entry_price
    else:
        effective_stop = -strategy.stop_loss_pct  # e.g. -0.10

    # 1. Partial exit — only if not already triggered
    if not partial_already_triggered and pnl_pct >= strategy.partial_exit_pct:
        return ExitDecision(
            should_exit=True,
            exit_all=False,    # sell only 50%
            reason=ExitReason.PARTIAL_PROFIT,
            detail=(
                f"Partial exit: +{pnl_pct:.1%} hit {strategy.partial_exit_pct:.0%} target. "
                f"Selling 50%, moving stop to breakeven."
            ),
        )

    # 2. Full take profit (second half)
    if partial_already_triggered and pnl_pct >= strategy.take_profit_pct:
        return ExitDecision(
            should_exit=True,
            exit_all=True,
            reason=ExitReason.TAKE_PROFIT,
            detail=f"Take profit: +{pnl_pct:.1%} (${position.unrealized_pnl:.2f})",
        )

    # 3. Stop loss (or breakeven stop after partial)
    if pnl_pct <= effective_stop:
        stop_label = "Breakeven stop" if partial_already_triggered else "Stop loss"
        return ExitDecision(
            should_exit=True,
            exit_all=True,
            reason=ExitReason.STOP_LOSS,
            detail=f"{stop_label}: {pnl_pct:.1%} (${position.unrealized_pnl:.2f})",
        )

    # 4. EOD hard close
    now_et = datetime.now(ET).time()
    eod = _parse_time(force_close_time)
    if now_et >= eod:
        return ExitDecision(
            should_exit=True,
            exit_all=True,
            reason=ExitReason.EOD_CLOSE,
            detail=f"Hard close at {force_close_time} ET",
        )

    # No exit
    stop_display = f"{effective_stop:.1%}"
    return ExitDecision(
        should_exit=False,
        exit_all=False,
        reason=ExitReason.NONE,
        detail=(
            f"Holding {position.ticker}: {pnl_pct:+.1%} | "
            f"TP={strategy.take_profit_pct:.0%} "
            f"partial={strategy.partial_exit_pct:.0%} "
            f"SL={stop_display}"
        ),
    )


def _parse_time(hhmm: str) -> time:
    h, m = hhmm.split(":")
    return time(int(h), int(m))
