"""
telegram_bot.py — Trade alerts + YES/NO approval flow.

Flow:
  1. Bot sends scan results to your Telegram
  2. You reply: YES MU  → bot executes the trade and monitors it
  3. Bot sends exit alerts (target hit, stop hit, EOD close)
  4. /stats  → today's P&L summary
  5. /positions → current open trades

Uses python-telegram-bot v21 (async). The approval listener runs as a
background polling loop inside APScheduler's thread.
"""
import logging
import asyncio
from datetime import datetime, timezone
from typing import Optional

from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, MAX_POSITION_SIZE, PHASE
from scorer import ScoredTicker
import alpaca_client as alpaca
import db

logger = logging.getLogger(__name__)

# Global bot instance (initialised once in start_listener)
_bot: Optional[Bot] = None
_app: Optional[Application] = None

# Pending approvals: ticker → ScoredTicker (waiting for YES response)
_pending: dict[str, ScoredTicker] = {}


# ---------------------------------------------------------------------------
# Send helpers
# ---------------------------------------------------------------------------

def _run(coro):
    """Run an async coroutine from sync code."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(coro)
        else:
            loop.run_until_complete(coro)
    except RuntimeError:
        asyncio.run(coro)


def send(text: str) -> None:
    """Send a plain text message to your Telegram chat."""
    async def _send():
        bot = Bot(token=TELEGRAM_TOKEN)
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=text, parse_mode="HTML")
    _run(_send())


def send_scan_results(picks: list[ScoredTicker], scan_time: str) -> None:
    """
    Send the morning scan results as a Telegram message.
    Stores picks in _pending so YES responses can trigger trades.
    """
    global _pending
    _pending = {s.ticker: s for s in picks[:5]}   # top 5 max

    if not picks:
        send(f"🔍 SCAN — {scan_time}\n\nNo qualifying picks today.")
        return

    lines = [f"🔍 <b>MORNING SCAN — {scan_time}</b>\n📈 <b>TOP PICKS:</b>\n"]

    for i, s in enumerate(picks[:5], 1):
        ind     = s.indicators
        cat     = f"📰 {s.catalyst_text[:80]}" if s.catalyst_found and s.catalyst_text else "📰 No clear catalyst"
        lines.append(
            f"{i}️⃣ <b>{s.ticker}</b> ${ind.price:.2f} ({ind.change_pct:+.1f}%) Score: {s.score}\n"
            f"   Entry: ${s.entry_price:.2f}  Stop: ${s.stop_loss:.2f}  Target: ${s.target:.2f}\n"
            f"   RSI: {ind.rsi:.0f}  Vol: {ind.volume_ratio:.1f}x  {cat}\n"
        )

    lines.append("\n✏️ Reply <b>YES [TICKER]</b> to approve a trade.\nExample: <code>YES MU</code>")
    lines.append(f"\n⚠️ {'Paper' if PHASE == 'paper' else 'LIVE'} trading · Max ${MAX_POSITION_SIZE:.0f}/trade")

    send("\n".join(lines))


def send_trade_opened(s: ScoredTicker, shares: int) -> None:
    ind = s.indicators
    send(
        f"✅ <b>TRADE OPENED</b>\n"
        f"<b>{s.ticker}</b> — {shares} shares @ ${s.entry_price:.2f}\n"
        f"Stop: ${s.stop_loss:.2f}  Target: ${s.target:.2f}  R/R: {s.rr_ratio:.1f}:1\n"
        f"RSI: {ind.rsi:.0f}  Vol: {ind.volume_ratio:.1f}x\n"
        f"{'📄 Paper' if PHASE == 'paper' else '💵 LIVE'} trade"
    )


def send_exit_alert(ticker: str, shares: int, entry: float, exit_price: float,
                    reason: str, pnl: float) -> None:
    emoji = "🟢" if pnl >= 0 else "🔴"
    send(
        f"{emoji} <b>TRADE CLOSED — {ticker}</b>\n"
        f"Exit: ${exit_price:.2f}  (Entry: ${entry:.2f})\n"
        f"P&L: <b>${pnl:+.2f}</b>  Reason: {reason}\n"
        f"{shares} shares"
    )


def send_circuit_breaker(reason: str) -> None:
    send(f"🚨 <b>CIRCUIT BREAKER — ALL TRADING HALTED</b>\n{reason}")


def send_daily_summary(date_str: str, total_pnl: float, wins: int, losses: int) -> None:
    emoji = "🟢" if total_pnl >= 0 else "🔴"
    send(
        f"{emoji} <b>DAILY SUMMARY — {date_str}</b>\n"
        f"P&L: <b>${total_pnl:+.2f}</b>  |  W/L: {wins}/{losses}"
    )


# ---------------------------------------------------------------------------
# Approval handler (runs in background polling loop)
# ---------------------------------------------------------------------------

async def _handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming Telegram messages. Looks for YES [TICKER] approval."""
    if update.effective_chat.id != TELEGRAM_CHAT_ID:
        return   # ignore messages from other chats

    text = (update.message.text or "").strip().upper()

    if text.startswith("YES "):
        ticker = text[4:].strip()
        if ticker in _pending:
            pick = _pending.pop(ticker)
            await _execute_approved_trade(pick, update)
        else:
            await update.message.reply_text(f"No pending pick for {ticker}. Run a scan first.")

    elif text == "/STATS":
        await _send_stats(update)

    elif text == "/POSITIONS":
        await _send_positions(update)


async def _execute_approved_trade(pick: ScoredTicker, update: Update) -> None:
    """Called when user replies YES [TICKER]. Executes the trade."""
    if db.is_halted():
        await update.message.reply_text("⚠️ Trading is halted today. No new trades.")
        return

    open_trades = db.get_open_trades()
    from config import MAX_POSITIONS
    if len(open_trades) >= MAX_POSITIONS:
        await update.message.reply_text(f"⚠️ Already at max {MAX_POSITIONS} positions. Exit one first.")
        return

    shares = alpaca.calculate_shares(pick.entry_price, MAX_POSITION_SIZE)
    if shares <= 0:
        await update.message.reply_text(f"⚠️ Cannot size position for {pick.ticker} at ${pick.entry_price:.2f}")
        return

    order_id = alpaca.buy(pick.ticker, shares)
    if order_id:
        trade_id = db.open_trade(
            scan_id=pick.ticker,   # using ticker as placeholder scan_id
            ticker=pick.ticker,
            entry_price=pick.entry_price,
            stop_loss=pick.stop_loss,
            target=pick.target,
            shares=shares,
            phase=PHASE,
        )
        db.set_state("positions_open", str(len(db.get_open_trades())))
        send_trade_opened(pick, shares)
    else:
        await update.message.reply_text(f"❌ Order failed for {pick.ticker}. Check logs.")


async def _send_stats(update: Update) -> None:
    trades = db.get_todays_closed_trades()
    if not trades:
        await update.message.reply_text("No closed trades today yet.")
        return
    total = sum(t.get("pnl_dollars", 0) or 0 for t in trades)
    wins  = sum(1 for t in trades if (t.get("pnl_dollars") or 0) > 0)
    await update.message.reply_text(
        f"📊 Today: {len(trades)} trades | W/L: {wins}/{len(trades)-wins} | P&L: ${total:+.2f}"
    )


async def _send_positions(update: Update) -> None:
    trades = db.get_open_trades()
    if not trades:
        await update.message.reply_text("No open positions.")
        return
    lines = ["📋 Open positions:"]
    for t in trades:
        pos = alpaca.get_open_position(t["ticker"])
        pnl = f"{pos['unrealized_pnl_pct']:+.1f}%" if pos else "?"
        lines.append(f"  {t['ticker']} — entry ${t['entry_price']:.2f} | now {pnl}")
    await update.message.reply_text("\n".join(lines))


# ---------------------------------------------------------------------------
# Start the background approval listener
# ---------------------------------------------------------------------------

def start_listener() -> None:
    """
    Start the Telegram polling loop in a background thread.
    Called once at bot startup.
    """
    import threading

    def _run_app():
        global _app

        async def _start():
            global _app
            _app = Application.builder().token(TELEGRAM_TOKEN).build()
            _app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _handle_message))
            _app.add_handler(CommandHandler("stats",     lambda u, c: _send_stats(u)))
            _app.add_handler(CommandHandler("positions", lambda u, c: _send_positions(u)))
            await _app.initialize()
            await _app.start()
            await _app.updater.start_polling(drop_pending_updates=True)
            # Block forever — thread exits when daemon is killed
            await asyncio.Event().wait()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_start())

    t = threading.Thread(target=_run_app, daemon=True)
    t.start()
    logger.info("Telegram listener started")
