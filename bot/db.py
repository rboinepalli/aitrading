"""
db.py — All Supabase operations for the momentum scanner.

Tables:
  scans         — every scan result (even stocks not traded)
  trades        — approved trades, full lifecycle
  daily_summary — EOD P&L summary
  bot_state     — key/value crash-recovery store
"""
import logging
from datetime import date, datetime, timezone
from typing import Optional

from supabase import create_client, Client
from config import SUPABASE_URL, SUPABASE_KEY

logger = logging.getLogger(__name__)
_db: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


# ---------------------------------------------------------------------------
# Scans
# ---------------------------------------------------------------------------

def log_scan(
    ticker: str,
    score: int,
    rsi: float,
    volume_ratio: float,
    price_at_scan: float,
    ema9_above: bool,
    ema20_above: bool,
    vwap_above: bool,
    catalyst_found: bool,
    catalyst_text: str,
    sector_etf: str,
    sector_etf_green: bool,
) -> str:
    """Insert a scan result. Returns the scan UUID."""
    result = _db.table("scans").insert({
        "ticker":          ticker,
        "score":           score,
        "rsi":             round(rsi, 2),
        "volume_ratio":    round(volume_ratio, 2),
        "price_at_scan":   round(price_at_scan, 4),
        "ema9_above":      ema9_above,
        "ema20_above":     ema20_above,
        "vwap_above":      vwap_above,
        "catalyst_found":  catalyst_found,
        "catalyst_text":   catalyst_text[:500] if catalyst_text else "",
        "sector_etf":      sector_etf,
        "sector_etf_green": sector_etf_green,
    }).execute()
    scan_id = result.data[0]["id"]
    logger.info("Scan logged: %s score=%d id=%s", ticker, score, scan_id)
    return scan_id


def get_unfilled_scans(days_ago: int = 1) -> list[dict]:
    """Return scan rows where price_1day_later is still NULL — for EOD fill job."""
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days_ago + 1)).isoformat()
    result = (
        _db.table("scans")
        .select("id, ticker, scanned_at, price_1day_later, price_2days_later")
        .is_("price_1day_later", "null")
        .lte("scanned_at", cutoff)
        .execute()
    )
    return result.data or []


def fill_scan_prices(scan_id: str, price_1d: Optional[float], price_2d: Optional[float]) -> None:
    update = {}
    if price_1d is not None:
        update["price_1day_later"] = round(price_1d, 4)
    if price_2d is not None:
        update["price_2days_later"] = round(price_2d, 4)
    if update:
        _db.table("scans").update(update).eq("id", scan_id).execute()


# ---------------------------------------------------------------------------
# Trades
# ---------------------------------------------------------------------------

def open_trade(
    scan_id: str,
    ticker: str,
    entry_price: float,
    stop_loss: float,
    target: float,
    shares: int,
    phase: str = "paper",
) -> str:
    """Insert a new open trade. Returns trade UUID."""
    result = _db.table("trades").insert({
        "scan_id":     scan_id,
        "ticker":      ticker,
        "phase":       phase,
        "entry_price": round(entry_price, 4),
        "stop_loss":   round(stop_loss, 4),
        "target":      round(target, 4),
        "shares":      shares,
        "entry_time":  datetime.now(timezone.utc).isoformat(),
    }).execute()
    trade_id = result.data[0]["id"]
    logger.info("Trade opened: %s @ $%.2f stop=$%.2f target=$%.2f id=%s",
                ticker, entry_price, stop_loss, target, trade_id)
    return trade_id


def close_trade(trade_id: str, exit_price: float, exit_reason: str, hold_hours: float) -> None:
    """Mark a trade as closed and compute P&L."""
    row = _db.table("trades").select("entry_price, shares").eq("id", trade_id).single().execute()
    entry_price = float(row.data["entry_price"])
    shares      = int(row.data["shares"])

    pnl_dollars = round((exit_price - entry_price) * shares, 2)
    pnl_percent = round((exit_price - entry_price) / entry_price * 100, 2)

    _db.table("trades").update({
        "exit_price":  round(exit_price, 4),
        "exit_time":   datetime.now(timezone.utc).isoformat(),
        "exit_reason": exit_reason,
        "pnl_dollars": pnl_dollars,
        "pnl_percent": pnl_percent,
        "hold_hours":  round(hold_hours, 1),
    }).eq("id", trade_id).execute()
    logger.info("Trade closed: id=%s reason=%s P&L=$%.2f (%.2f%%)",
                trade_id, exit_reason, pnl_dollars, pnl_percent)


def get_open_trades() -> list[dict]:
    """Return all trades where exit_time IS NULL."""
    result = (
        _db.table("trades")
        .select("*")
        .is_("exit_time", "null")
        .execute()
    )
    return result.data or []


def get_todays_closed_trades() -> list[dict]:
    today = date.today().isoformat()
    result = (
        _db.table("trades")
        .select("pnl_dollars, ticker, exit_reason")
        .gte("exit_time", today)
        .not_.is_("exit_time", "null")
        .execute()
    )
    return result.data or []


# ---------------------------------------------------------------------------
# Daily summary
# ---------------------------------------------------------------------------

def upsert_daily_summary(
    trading_date: date,
    trades_taken: int,
    trades_won: int,
    trades_lost: int,
    total_pnl: float,
    avg_hold_hrs: float,
    best_ticker: str,
    worst_ticker: str,
) -> None:
    _db.table("daily_summary").upsert({
        "date":         trading_date.isoformat(),
        "trades_taken": trades_taken,
        "trades_won":   trades_won,
        "trades_lost":  trades_lost,
        "total_pnl":    round(total_pnl, 2),
        "avg_hold_hrs": round(avg_hold_hrs, 1) if avg_hold_hrs else None,
        "best_ticker":  best_ticker,
        "worst_ticker": worst_ticker,
    }).execute()


# ---------------------------------------------------------------------------
# Bot state (crash recovery)
# ---------------------------------------------------------------------------

def get_state(key: str, default: str = "") -> str:
    result = _db.table("bot_state").select("value").eq("key", key).execute()
    return result.data[0]["value"] if result.data else default


def set_state(key: str, value: str) -> None:
    _db.table("bot_state").upsert({"key": key, "value": str(value)}).execute()


def get_daily_loss() -> float:
    return float(get_state("daily_loss", "0"))


def add_daily_loss(amount: float) -> float:
    """Add to today's loss tracker. Returns new total."""
    total = get_daily_loss() + amount
    set_state("daily_loss", str(round(total, 2)))
    return total


def is_halted() -> bool:
    return get_state("trading_halted", "false").lower() == "true"


def halt_trading(reason: str) -> None:
    set_state("trading_halted", "true")
    set_state("halt_reason", reason)
    logger.warning("Trading HALTED: %s", reason)


def reset_daily_state() -> None:
    """Call at start of each trading day to reset loss tracker and halt flag."""
    set_state("daily_loss", "0")
    set_state("trading_halted", "false")
    set_state("halt_reason", "")
    set_state("positions_open", "0")
    logger.info("Daily state reset")
