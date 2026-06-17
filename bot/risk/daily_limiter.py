"""
risk/daily_limiter.py — Per-strategy daily loss circuit breaker.

v2 change: one DailyLimiter instance per strategy, each tracking its own P&L.

Why per-strategy?
  If Strategy A hits -$500 today, we don't want to also halt Strategy B
  which may be in a completely different state. They're independent bets.

How it works:
  Each strategy tracks its own closed trade P&L for the day in Supabase.
  If a strategy's daily P&L hits -MAX_DAILY_LOSS, that strategy stops
  opening new positions for the rest of the day.
"""

import logging
from datetime import date

logger = logging.getLogger(__name__)


class DailyLimiter:
    """Tracks one strategy's daily P&L and enforces its loss limit."""

    def __init__(self, strategy_name: str, max_daily_loss_usd: float, db):
        self._strategy = strategy_name
        self._max_loss = max_daily_loss_usd
        self._db = db                          # SupabaseDB instance
        self._halt_date: date | None = None

    def is_halted(self) -> bool:
        """
        Return True if this strategy should stop trading today.
        Re-queries Supabase each call so it survives bot restarts mid-day.
        """
        today = date.today()

        if self._halt_date == today:
            return True

        daily_pnl = self._get_daily_pnl(today)

        if daily_pnl <= -self._max_loss:
            logger.warning(
                "%s daily loss limit hit: $%.2f (limit -$%.2f). Halting today.",
                self._strategy, daily_pnl, self._max_loss,
            )
            self._halt_date = today
            return True

        return False

    def _get_daily_pnl(self, today: date) -> float:
        """Sum of all closed trade P&L for this strategy today."""
        trades = self._db.get_todays_trades(today, strategy=self._strategy)
        pnls = [t["pnl"] for t in trades if t.get("pnl") is not None]
        return sum(pnls)
