"""
exits/exit_manager.py — Position exit logic.

Three exit conditions, checked in priority order:
  1. Take profit  → unrealized gain >= +15%  (lock in the win)
  2. Stop loss    → unrealized loss <= -10%  (cut the loss)
  3. EOD close    → current time >= 3:45pm ET (exit before market close)

Why a hard EOD close?
  Leveraged ETFs (TQQQ, SQQQ) use daily rebalancing and decay over time when held
  overnight. Closing by 3:45pm gives 15 minutes of buffer before the 4pm close
  and avoids overnight decay risk in v1 (swing trades come in v2).

Why these specific percentages?
  +15% / -10% gives a 1.5:1 reward-to-risk ratio, which is a common minimum
  threshold for viable trading strategies. On a 3x leveraged ETF like TQQQ,
  a +15% gain means the underlying QQQ only moved +5%.
"""

import logging
from dataclasses import dataclass
from enum import Enum
from datetime import datetime, time

import pytz

from broker.alpaca_client import OpenPosition
from config import Config

logger = logging.getLogger(__name__)

ET = pytz.timezone("America/New_York")  # all market logic runs in Eastern Time


class ExitReason(str, Enum):
    """
    Why we're closing a position.
    Stored in the trades table exit_reason column.
    """
    TAKE_PROFIT = "TAKE_PROFIT"
    STOP_LOSS = "STOP_LOSS"
    EOD_CLOSE = "EOD_CLOSE"
    NONE = "NONE"   # no exit triggered


@dataclass
class ExitDecision:
    """Result of checking whether to exit a position."""
    should_exit: bool
    reason: ExitReason
    detail: str     # human-readable explanation (useful for logs + Telegram in v2)


def check_exit(position: OpenPosition, cfg: Config) -> ExitDecision:
    """
    Evaluate all exit conditions for an open position.

    Args:
        position: The current open position from Alpaca
        cfg:      Bot configuration (thresholds, EOD time)

    Returns:
        ExitDecision — includes whether to exit and the reason why.
    """
    # 1. Take profit — unrealized P&L is already a decimal from Alpaca
    if position.unrealized_pnl_pct >= cfg.take_profit_pct:
        return ExitDecision(
            should_exit=True,
            reason=ExitReason.TAKE_PROFIT,
            detail=(
                f"Take profit hit: +{position.unrealized_pnl_pct:.1%} "
                f"(${position.unrealized_pnl:.2f})"
            ),
        )

    # 2. Stop loss — pnl_pct is negative for losses
    if position.unrealized_pnl_pct <= -cfg.stop_loss_pct:
        return ExitDecision(
            should_exit=True,
            reason=ExitReason.STOP_LOSS,
            detail=(
                f"Stop loss hit: {position.unrealized_pnl_pct:.1%} "
                f"(${position.unrealized_pnl:.2f})"
            ),
        )

    # 3. EOD hard close — check the wall clock in ET
    now_et = datetime.now(ET)
    eod_time = _parse_time(cfg.eod_close_time)

    if now_et.time() >= eod_time:
        return ExitDecision(
            should_exit=True,
            reason=ExitReason.EOD_CLOSE,
            detail=f"EOD hard close at {now_et.strftime('%H:%M')} ET",
        )

    # No exit triggered
    return ExitDecision(
        should_exit=False,
        reason=ExitReason.NONE,
        detail=(
            f"Holding: {position.unrealized_pnl_pct:.1%} | "
            f"TP={cfg.take_profit_pct:.0%} SL=-{cfg.stop_loss_pct:.0%}"
        ),
    )


def _parse_time(hhmm: str) -> time:
    """
    Convert a "HH:MM" string to a datetime.time object.
    e.g. "15:45" → time(15, 45)

    TypeScript analogy: parsing a time string into a comparable value.
    """
    parts = hhmm.split(":")
    return time(int(parts[0]), int(parts[1]))
