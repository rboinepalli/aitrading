"""
db/supabase_client.py — Database read/write operations via Supabase.

Supabase gives us a Postgres database with a REST API and a Python client.
We use the SERVICE KEY here (full DB access) — never expose this in the browser.

Think of this module as your "data access layer" or "repository" —
it translates between Python objects and database rows.

TypeScript analogy: a Prisma client or a Supabase client in a Next.js API route.
The difference: we're on the server (Railway worker), so using the service key is safe.

Supabase client usage:
  client.table("trades").insert({...}).execute()   ← like an ORM query
  client.table("trades").update({...}).eq("id", id).execute()
"""

import logging
from datetime import date, datetime
from typing import Optional

from supabase import create_client, Client

from config import Config
from signals.entry import EntrySignal
from signals.regime import Regime

logger = logging.getLogger(__name__)


class SupabaseDB:
    """All database operations for the trading bot."""

    def __init__(self, cfg: Config):
        # create_client returns a Supabase client authenticated with the service key.
        # The service key bypasses Row Level Security (RLS), giving full write access.
        self._db: Client = create_client(cfg.supabase_url, cfg.supabase_service_key)
        logger.info("Supabase connected to %s", cfg.supabase_url)

    # -----------------------------------------------------------------------
    # Trades
    # -----------------------------------------------------------------------

    def insert_trade(
        self,
        ticker: str,
        entry_price: float,
        shares: int,
        entry_time: datetime,
        regime: Regime,
    ) -> str:
        """
        Insert a new open trade. Returns the UUID assigned by Postgres.
        The exit fields (exit_price, exit_time, pnl, exit_reason) start as NULL.
        """
        result = (
            self._db.table("trades")
            .insert({
                "ticker": ticker,
                "entry_price": entry_price,
                "shares": shares,
                "entry_time": entry_time.isoformat(),
                "regime": regime.value,  # Regime enum → string via .value
            })
            .execute()
        )
        trade_id = result.data[0]["id"]
        logger.info("Trade inserted: id=%s %s x%d @ $%.2f", trade_id, ticker, shares, entry_price)
        return trade_id

    def close_trade(
        self,
        trade_id: str,
        exit_price: float,
        exit_time: datetime,
        exit_reason: str,
        pnl: float,
    ) -> None:
        """Update an open trade row with exit details when the position is closed."""
        self._db.table("trades").update({
            "exit_price": exit_price,
            "exit_time": exit_time.isoformat(),
            "exit_reason": exit_reason,
            "pnl": round(pnl, 2),
        }).eq("id", trade_id).execute()

        logger.info(
            "Trade closed: id=%s | reason=%s | P&L=$%.2f",
            trade_id, exit_reason, pnl,
        )

    def get_open_trade_id(self, ticker: str) -> Optional[str]:
        """
        Return the UUID of the currently open trade for a ticker, or None.
        Used to find the trade row to update when closing a position.
        """
        result = (
            self._db.table("trades")
            .select("id")
            .eq("ticker", ticker)
            .is_("exit_time", "null")       # exit_time IS NULL → trade is open
            .limit(1)
            .execute()
        )
        if result.data:
            return result.data[0]["id"]
        return None

    # -----------------------------------------------------------------------
    # Signals
    # -----------------------------------------------------------------------

    def insert_signal(self, entry_signal: EntrySignal) -> None:
        """Log every signal evaluation for audit and strategy tuning."""
        self._db.table("signals").insert({
            "ticker": entry_signal.ticker,
            "ts": datetime.utcnow().isoformat(),
            "regime": entry_signal.regime.value,
            "rsi": round(entry_signal.rsi, 2),
            "ema_fast": round(entry_signal.ema_fast, 4),
            "ema_slow": round(entry_signal.ema_slow, 4),
            "vix": round(entry_signal.vix, 2),
            "signal": entry_signal.signal.value,
        }).execute()

    # -----------------------------------------------------------------------
    # Daily summary
    # -----------------------------------------------------------------------

    def upsert_daily_summary(
        self,
        trading_date: date,
        total_pnl: float,
        trades_taken: int,
        winning_trades: int,
        losing_trades: int,
        max_drawdown: float,
        regime_at_close: str,
    ) -> None:
        """
        Write (or overwrite) the daily summary for a given date.
        `upsert` = insert if not exists, update if exists (based on the UNIQUE date column).
        """
        self._db.table("daily_summary").upsert({
            "date": trading_date.isoformat(),
            "total_pnl": round(total_pnl, 2),
            "trades_taken": trades_taken,
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "max_drawdown": round(max_drawdown, 2),
            "regime_at_close": regime_at_close,
        }).execute()

        logger.info(
            "Daily summary: date=%s | P&L=$%.2f | trades=%d",
            trading_date, total_pnl, trades_taken,
        )

    def get_todays_trades(self, trading_date: date) -> list[dict]:
        """
        Return all closed trades for today. Used to compute the daily summary.
        """
        result = (
            self._db.table("trades")
            .select("pnl, exit_reason")
            .gte("entry_time", trading_date.isoformat())   # entry_time >= today
            .not_.is_("exit_time", "null")                  # only closed trades
            .execute()
        )
        return result.data or []
