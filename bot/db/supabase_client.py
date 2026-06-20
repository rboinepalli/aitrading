"""
db/supabase_client.py — Database operations (v2).

v2 adds:
  - strategy field on all trades/signals
  - conviction_score and signals_triggered on trades
  - partial_exit_triggered and stop_price tracking
  - bot_events table writes
  - get_todays_trades accepts strategy filter
"""

import logging
from datetime import date, datetime, timezone
from typing import Optional

from supabase import create_client, Client

from config import Config

logger = logging.getLogger(__name__)


class SupabaseDB:
    """All database operations for the trading bot."""

    def __init__(self, cfg: Config):
        self._db: Client = create_client(cfg.supabase_url, cfg.supabase_service_key)
        logger.info("Supabase connected to %s", cfg.supabase_url)

    # -----------------------------------------------------------------------
    # Trades
    # -----------------------------------------------------------------------

    def insert_trade(
        self,
        strategy: str,
        ticker: str,
        entry_price: float,
        shares: int,
        entry_time: datetime,
        regime: str,
        conviction_score: int,
        signals_triggered: list[str],
    ) -> str:
        """Insert a new open trade. Returns the UUID."""
        result = (
            self._db.table("trades")
            .insert({
                "strategy": strategy,
                "ticker": ticker,
                "entry_price": entry_price,
                "shares": shares,
                "entry_time": entry_time.isoformat(),
                "regime": regime,
                "conviction_score": conviction_score,
                "signals_triggered": signals_triggered,
                "status": "OPEN",
                "partial_exit_triggered": False,
                "stop_price": entry_price,   # starts at entry, moves to breakeven after partial
            })
            .execute()
        )
        trade_id = result.data[0]["id"]
        logger.info(
            "Trade inserted: id=%s %s %s x%d @ $%.2f score=%d",
            trade_id, strategy, ticker, shares, entry_price, conviction_score,
        )
        return trade_id

    def mark_partial_exit(self, trade_id: str, stop_price: float) -> None:
        """After selling 50%, mark partial exit and set initial trailing stop price."""
        self._db.table("trades").update({
            "partial_exit_triggered": True,
            "stop_price": stop_price,
        }).eq("id", trade_id).execute()
        logger.info("Partial exit marked for trade %s, trailing stop set to $%.2f", trade_id, stop_price)

    def update_stop_price(self, trade_id: str, stop_price: float) -> None:
        """Ratchet the trailing stop price upward as price moves in our favour."""
        self._db.table("trades").update({"stop_price": stop_price}).eq("id", trade_id).execute()
        logger.info("Trailing stop updated for trade %s → $%.2f", trade_id, stop_price)

    def close_trade(
        self,
        trade_id: str,
        exit_price: float,
        exit_time: datetime,
        exit_reason: str,
        pnl: float,
    ) -> None:
        """Update trade row when position is fully closed."""
        status = "CLOSED_GAIN" if pnl >= 0 else "CLOSED_LOSS"
        self._db.table("trades").update({
            "exit_price": exit_price,
            "exit_time": exit_time.isoformat(),
            "exit_reason": exit_reason,
            "pnl": round(pnl, 2),
            "status": status,
        }).eq("id", trade_id).execute()
        logger.info("Trade closed: id=%s reason=%s P&L=$%.2f", trade_id, exit_reason, pnl)

    def get_open_trade(self, ticker: str, strategy: str) -> Optional[dict]:
        """Return the open trade row for a ticker+strategy, or None."""
        result = (
            self._db.table("trades")
            .select("id, shares, entry_price, partial_exit_triggered, stop_price, entry_time")
            .eq("ticker", ticker)
            .eq("strategy", strategy)
            .eq("status", "OPEN")
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    def get_open_trade_by_id(self, trade_id: str) -> Optional[dict]:
        """Return an open trade row by ID — used to detect manual closes."""
        result = (
            self._db.table("trades")
            .select("id")
            .eq("id", trade_id)
            .eq("status", "OPEN")
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    # -----------------------------------------------------------------------
    # Signals
    # -----------------------------------------------------------------------

    def insert_signal(
        self,
        strategy: str,
        ticker: str,
        regime: str,
        rsi: float,
        ema_fast: float,
        ema_slow: float,
        macd: float,
        vwap: float,
        volume_ratio: float,
        vix: float,
        conviction_score: int,
        signal: str,            # "BUY" or "NONE"
        skip_reason: str = "",
    ) -> None:
        """Log every signal evaluation for audit and strategy tuning."""
        self._db.table("signals").insert({
            "strategy": strategy,
            "ticker": ticker,
            "ts": datetime.now(timezone.utc).isoformat(),
            "regime": regime,
            "rsi": round(rsi, 2),
            "ema_fast": round(ema_fast, 4),
            "ema_slow": round(ema_slow, 4),
            "macd": round(macd, 6),
            "vwap": round(vwap, 4),
            "volume_ratio": round(volume_ratio, 2),
            "vix": round(vix, 2),
            "conviction_score": conviction_score,
            "signal": signal,
        }).execute()

    # -----------------------------------------------------------------------
    # Bot events
    # -----------------------------------------------------------------------

    def log_event(self, event_type: str, message: str, strategy: str = None) -> None:
        """
        Write a bot event to the bot_events table.
        The dashboard reads this to show status like "CHOPPY — sitting out".

        event_type: STARTED / REGIME_CHANGE / SKIPPED_TRADE / DAILY_LIMIT_HIT / ERROR
        """
        self._db.table("bot_events").insert({
            "event_type": event_type,
            "strategy": strategy,
            "message": message,
        }).execute()
        logger.info("Event logged: [%s] %s", event_type, message)

    # -----------------------------------------------------------------------
    # Daily summary
    # -----------------------------------------------------------------------

    def get_todays_trades(self, trading_date: date, strategy: str = None) -> list[dict]:
        """Return all closed trades for today, optionally filtered by strategy."""
        query = (
            self._db.table("trades")
            .select("pnl, exit_reason, strategy")
            .gte("entry_time", trading_date.isoformat())
            .eq("status", "CLOSED_GAIN")  # use status instead of NULL check
        )
        # Supabase .or_() for multiple status values
        query = (
            self._db.table("trades")
            .select("pnl, exit_reason, strategy")
            .gte("entry_time", trading_date.isoformat())
            .not_.is_("exit_time", "null")
        )
        if strategy:
            query = query.eq("strategy", strategy)

        result = query.execute()
        return result.data or []

    def upsert_daily_summary(
        self,
        trading_date: date,
        total_pnl: float,
        trades_taken: int,
        winning_trades: int,
        losing_trades: int,
        max_drawdown: float,
        regime_at_close: str,
        strategy_a_pnl: float = 0,
        strategy_b_pnl: float = 0,
        strategy_a_trades: int = 0,
        strategy_b_trades: int = 0,
    ) -> None:
        self._db.table("daily_summary").upsert({
            "date": trading_date.isoformat(),
            "total_pnl": round(total_pnl, 2),
            "trades_taken": trades_taken,
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "max_drawdown": round(max_drawdown, 2),
            "regime_at_close": regime_at_close,
            "strategy_a_pnl": round(strategy_a_pnl, 2),
            "strategy_b_pnl": round(strategy_b_pnl, 2),
            "strategy_a_trades": strategy_a_trades,
            "strategy_b_trades": strategy_b_trades,
        }).execute()
        logger.info("Daily summary upserted: date=%s total=$%.2f", trading_date, total_pnl)
