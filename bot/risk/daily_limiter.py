"""
risk/daily_limiter.py — Daily loss circuit breaker.

If the bot loses more than $500 in a single day, it stops placing new trades.
This is a hard rule — not negotiable — and is the most important safety net.

Why a daily loss limit?
  Without a circuit breaker, a strategy that starts losing can spiral quickly,
  especially with leveraged ETFs where moves are amplified 3x.
  $500 is 25% of the $2,000 max position — losing this much in a day means
  the strategy is likely not working in the current conditions.

How it works:
  - We query Alpaca for today's realized P&L at the start of each loop iteration.
  - If P&L <= -$500, we set a flag and skip all entry logic for the rest of the day.
  - The flag resets on the next trading day (bot restarts or day changes).

Note: This checks REALIZED P&L only (closed trades).
  Unrealized losses on open positions are handled by the stop loss.
"""

import logging
from datetime import date

from broker.alpaca_client import AlpacaClient
from config import Config

logger = logging.getLogger(__name__)


class DailyLimiter:
    """
    Tracks daily P&L and enforces the maximum daily loss rule.

    TypeScript analogy: a stateful service class with a private flag.
    In Python, `self` is the equivalent of `this` in TypeScript.
    """

    def __init__(self, cfg: Config, alpaca: AlpacaClient):
        self._cfg = cfg
        self._alpaca = alpaca
        self._halt_date: date | None = None  # date when the limit was hit

    def is_halted(self) -> bool:
        """
        Return True if trading is halted for today due to daily loss limit.

        We re-check the actual P&L from Alpaca each call rather than
        relying solely on the flag, in case of restarts mid-day.
        """
        today = date.today()

        # If already halted today, no need to re-query Alpaca
        if self._halt_date == today:
            return True

        # Ask Alpaca for today's realized P&L
        daily_pnl = self._alpaca.get_daily_pnl()

        if daily_pnl <= -self._cfg.max_daily_loss_usd:
            logger.warning(
                "Daily loss limit hit: $%.2f (limit: -$%.2f). "
                "No new trades today.",
                daily_pnl, self._cfg.max_daily_loss_usd,
            )
            self._halt_date = today
            return True

        return False

    def get_daily_pnl(self) -> float:
        """Return today's P&L in dollars (negative means loss)."""
        return self._alpaca.get_daily_pnl()
