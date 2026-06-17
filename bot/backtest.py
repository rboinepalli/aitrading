#!/usr/bin/env python3
"""
backtest.py — Offline strategy backtesting.

Usage:
  python backtest.py                  # last 3 months
  python backtest.py --months 6       # last 6 months
  python backtest.py --start 2025-01-01 --end 2025-06-17

What it does:
  1. Fetches historical bars from Alpaca IEX (same source as live bot)
  2. Replays the strategy day-by-day, bar-by-bar (every 5 minutes)
  3. Applies the same conviction scoring and entry/exit rules as the live bot
  4. Pushes results to Supabase → visible in the dashboard Backtest tab

This runs locally on your laptop — Railway is not involved.
Results go into three Supabase tables: backtest_runs, backtest_trades, backtest_equity.
"""

import argparse
import logging
import math
import sys
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pytz
from dotenv import load_dotenv

load_dotenv()

# Import bot modules (run from bot/ directory)
from config import load_config
from data.market_data import MarketDataClient, _normalise
from db.supabase_client import SupabaseDB
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.data.enums import DataFeed

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

ET = pytz.timezone("America/New_York")


# ---------------------------------------------------------------------------
# Indicator math — mirrors signals/indicators.py but takes bar slices directly
# (no API calls — all data is pre-fetched before the replay loop)
# ---------------------------------------------------------------------------

def _ema(closes: pd.Series, period: int) -> pd.Series:
    return closes.ewm(span=period, adjust=False).mean()


def _rsi(closes: pd.Series, period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    delta = closes.diff()
    gains = delta.clip(lower=0).ewm(com=period - 1, adjust=False).mean()
    losses = (-delta.clip(upper=0)).ewm(com=period - 1, adjust=False).mean()
    rs = gains / losses
    return float((100 - (100 / (1 + rs))).iloc[-1])


def _macd_cross(closes: pd.Series) -> bool:
    """True if MACD line crossed above signal line on the last bar."""
    if len(closes) < 27:
        return False
    macd = _ema(closes, 12) - _ema(closes, 26)
    signal = macd.ewm(span=9, adjust=False).mean()
    return float(macd.iloc[-2]) < float(signal.iloc[-2]) and float(macd.iloc[-1]) > float(signal.iloc[-1])


def _vwap(df: pd.DataFrame) -> float:
    typical = (df["High"] + df["Low"] + df["Close"]) / 3
    return float((typical * df["Volume"]).cumsum().iloc[-1] / df["Volume"].cumsum().iloc[-1])


def score_slice(intraday: pd.DataFrame, daily: pd.DataFrame,
                rsi_oversold: float, vol_threshold: float) -> tuple[int, list[str]]:
    """
    Compute conviction score from pre-fetched bar slices.
    Same 6-signal, 0-8 point system as the live scorer.
    Returns (score, signals_fired).
    """
    if len(intraday) < 30:
        return 0, []

    closes  = intraday["Close"]
    volumes = intraday["Volume"]
    price   = float(closes.iloc[-1])

    rsi      = _rsi(closes)
    ema20    = float(_ema(closes, 20).iloc[-1])
    macd_hit = _macd_cross(closes)

    vol_avg  = volumes.rolling(20).mean().iloc[-1]
    vol_ratio = float(volumes.iloc[-1] / vol_avg) if vol_avg > 0 else 1.0

    # VWAP uses only today's bars — index is UTC, same calendar day as ET open
    today_date = intraday.index[-1].date()
    today_bars = intraday[intraday.index.date == today_date]
    vwap = _vwap(today_bars) if len(today_bars) > 1 else price

    five_day = len(daily) >= 6 and float(daily["Close"].iloc[-1]) > float(daily["Close"].iloc[-6])

    score, fired = 0, []
    if rsi < rsi_oversold:      score += 2; fired.append("RSI")
    if price > ema20:           score += 1; fired.append("EMA20")
    if macd_hit:                score += 2; fired.append("MACD")
    if vol_ratio >= vol_threshold: score += 1; fired.append("VOLUME")
    if price > vwap:            score += 1; fired.append("VWAP")
    if five_day:                score += 1; fired.append("5DAY")

    return score, fired


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def regime_for_day(spy_daily: pd.DataFrame, day: date) -> str:
    """BULL if SPY is above its 200-DMA on this day, else BEAR."""
    mask = spy_daily.index.date <= day
    subset = spy_daily[mask]
    if len(subset) < 200:
        return "BULL"
    price  = float(subset["Close"].iloc[-1])
    sma200 = float(subset["Close"].rolling(200).mean().iloc[-1])
    return "BULL" if price > sma200 else "BEAR"


def time_window(ts) -> str:
    """PRIMARY / DEAD_ZONE / POWER_HOUR / CLOSED for a bar timestamp."""
    from datetime import time as dtime
    t = ts.tz_convert(ET).time() if ts.tzinfo else ts.time()
    if dtime(9, 30) <= t < dtime(11, 0):  return "PRIMARY"
    if dtime(11, 0) <= t < dtime(14, 0):  return "DEAD_ZONE"
    if dtime(14, 0) <= t < dtime(15, 30): return "POWER_HOUR"
    return "CLOSED"


def min_score(window: str) -> int:
    return {"PRIMARY": 5, "POWER_HOUR": 6}.get(window, 0)


def fetch_full_intraday(client, ticker: str, days: int) -> pd.DataFrame:
    """Fetch a long run of 5-min bars at once (for backtest replay)."""
    end   = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    try:
        bars = client.get_stock_bars(StockBarsRequest(
            symbol_or_symbols=ticker,
            timeframe=TimeFrame(5, TimeFrameUnit.Minute),
            start=start, end=end,
            feed=DataFeed.IEX,
        ))
        return _normalise(bars.df, ticker)
    except Exception as exc:
        logger.error("fetch_full_intraday(%s): %s", ticker, exc)
        return pd.DataFrame()


# ---------------------------------------------------------------------------
# Backtest engine
# ---------------------------------------------------------------------------

class BacktestEngine:
    """
    Replays the live bot strategy on historical bars.

    For each 5-minute bar in the backtest period:
      1. Determine regime (BULL/BEAR) from SPY 200-DMA
      2. Determine time window (PRIMARY / POWER_HOUR / skip others)
      3. Score each strategy's tickers via conviction scoring
      4. Simulate entries and exits using the same rules as the live bot

    No API calls happen inside the replay loop — all data is pre-fetched.
    """

    def __init__(self, data_client: MarketDataClient, cfg, start: date, end: date):
        self._data   = data_client
        self._cfg    = cfg
        self.start   = start
        self.end     = end
        self.trades: list[dict] = []
        self.daily_pnl: dict[date, float] = {}

    def run(self) -> dict:
        days = (self.end - self.start).days + 280  # +280 = 200-DMA warmup + weekends

        # ── Fetch all data upfront ──────────────────────────────────────────
        logger.info("Fetching SPY daily bars...")
        spy_daily = self._data.get_daily_bars("SPY", days=days)
        if spy_daily.empty:
            raise RuntimeError("Could not fetch SPY daily bars from Alpaca")

        all_tickers = list(dict.fromkeys(
            self._cfg.strategy_a.tickers + self._cfg.strategy_b.tickers
        ))

        logger.info("Fetching 5-min bars for %d tickers...", len(all_tickers))
        intraday: dict[str, pd.DataFrame] = {}
        daily:    dict[str, pd.DataFrame] = {}
        for ticker in all_tickers:
            logger.info("  %s...", ticker)
            intraday[ticker] = fetch_full_intraday(self._data._client, ticker, days)
            daily[ticker]    = self._data.get_daily_bars(ticker, days=days)

        # ── Determine trading days in range ─────────────────────────────────
        spy_daily.index = pd.to_datetime(spy_daily.index)
        spy_dates = (spy_daily.index.tz_convert("UTC") if spy_daily.index.tz else spy_daily.index).date
        trading_days = [d for d in spy_dates if self.start <= d <= self.end]
        logger.info("Replaying %d trading days (%s → %s)", len(trading_days), self.start, self.end)

        # ── Replay ──────────────────────────────────────────────────────────
        # open_pos: strategy_name → {ticker, entry_price, shares, score, partial, stop_price}
        open_pos: dict[str, dict] = {}

        for day in trading_days:
            day_pnl = 0.0

            regime = regime_for_day(spy_daily, day)

            # Collect all 5-min timestamps for this day
            day_timestamps: set = set()
            for df in intraday.values():
                if df.empty:
                    continue
                mask = df.index.date == day
                day_timestamps.update(df.index[mask].tolist())
            if not day_timestamps:
                self.daily_pnl[day] = 0.0
                continue

            for ts in sorted(day_timestamps):
                window = time_window(ts)

                # ── Exits (run in every window including CLOSED for EOD) ──
                for strat in list(open_pos.keys()):
                    pos    = open_pos[strat]
                    ticker = pos["ticker"]
                    df     = intraday.get(ticker)
                    if df is None or ts not in df.index:
                        continue

                    current = float(df.loc[ts, "Close"])
                    pnl_pct = (current - pos["entry_price"]) / pos["entry_price"]
                    strat_cfg = self._cfg.strategy_a if strat == "aggressive_3x" else self._cfg.strategy_b

                    exit_reason = None

                    if window == "CLOSED":
                        exit_reason = "EOD_CLOSE"
                    elif not pos["partial"] and pnl_pct >= strat_cfg.partial_exit_pct:
                        half = max(1, pos["shares"] // 2)
                        pnl  = half * (current - pos["entry_price"])
                        self._record(strat, pos, current, half, pnl, "PARTIAL_PROFIT", regime, day)
                        day_pnl += pnl
                        pos["shares"]     -= half
                        pos["partial"]     = True
                        pos["stop_price"]  = pos["entry_price"]
                        continue
                    elif pos["partial"] and pnl_pct >= strat_cfg.take_profit_pct:
                        exit_reason = "TAKE_PROFIT"
                    elif pnl_pct <= -strat_cfg.stop_loss_pct:
                        exit_reason = "STOP_LOSS"

                    if exit_reason:
                        pnl = pos["shares"] * (current - pos["entry_price"])
                        self._record(strat, pos, current, pos["shares"], pnl, exit_reason, regime, day)
                        day_pnl += pnl
                        del open_pos[strat]

                # ── Entries (PRIMARY and POWER_HOUR only) ───────────────────
                if window not in ("PRIMARY", "POWER_HOUR"):
                    continue
                req_score = min_score(window)

                # Strategy A
                if "aggressive_3x" not in open_pos:
                    ticker_a = (self._cfg.strategy_a.tickers[0] if regime == "BULL"
                                else self._cfg.strategy_a.tickers[1])
                    score, _ = self._score_at(ticker_a, ts, day, intraday, daily)
                    if score >= req_score:
                        price  = float(intraday[ticker_a].loc[ts, "Close"])
                        shares = math.floor(self._cfg.max_per_trade_usd / price)
                        if shares > 0:
                            open_pos["aggressive_3x"] = {
                                "ticker": ticker_a, "entry_price": price,
                                "shares": shares, "score": score,
                                "partial": False, "stop_price": None,
                            }

                # Strategy B (BULL only)
                if "conservative_multi" not in open_pos and regime == "BULL":
                    best_score, best_ticker = 0, None
                    for ticker in self._cfg.strategy_b.tickers:
                        score, _ = self._score_at(ticker, ts, day, intraday, daily)
                        if score > best_score:
                            best_score, best_ticker = score, ticker

                    if best_score >= req_score and best_ticker:
                        price  = float(intraday[best_ticker].loc[ts, "Close"])
                        shares = math.floor(self._cfg.max_per_trade_usd / price)
                        if shares > 0:
                            open_pos["conservative_multi"] = {
                                "ticker": best_ticker, "entry_price": price,
                                "shares": shares, "score": best_score,
                                "partial": False, "stop_price": None,
                            }

            self.daily_pnl[day] = round(day_pnl, 2)

        return self._summary()

    def _score_at(self, ticker: str, ts, day: date,
                  intraday: dict, daily: dict) -> tuple[int, list]:
        df = intraday.get(ticker)
        if df is None or df.empty:
            return 0, []
        intra_slice = df[df.index <= ts].tail(100)  # last 100 bars for indicator warmup
        day_slice   = daily.get(ticker, pd.DataFrame())
        if not day_slice.empty:
            day_dates = (day_slice.index.tz_convert("UTC") if day_slice.index.tz
                         else day_slice.index).date
            day_slice = day_slice[day_dates <= day]
        return score_slice(intra_slice, day_slice,
                           self._cfg.rsi_oversold, self._cfg.volume_ratio_threshold)

    def _record(self, strat, pos, exit_price, shares, pnl, reason, regime, day):
        self.trades.append({
            "strategy":       strat,
            "ticker":         pos["ticker"],
            "entry_date":     day,
            "entry_price":    pos["entry_price"],
            "exit_price":     exit_price,
            "shares":         shares,
            "pnl":            round(pnl, 2),
            "exit_reason":    reason,
            "conviction_score": pos["score"],
            "regime":         regime,
        })

    def _summary(self) -> dict:
        pnls   = [t["pnl"] for t in self.trades]
        wins   = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]

        # Max drawdown: largest peak-to-trough on cumulative P&L
        cumulative, peak, max_dd = 0.0, 0.0, 0.0
        for p in pnls:
            cumulative += p
            peak = max(peak, cumulative)
            max_dd = max(max_dd, peak - cumulative)

        a_trades = [t for t in self.trades if t["strategy"] == "aggressive_3x"]
        b_trades = [t for t in self.trades if t["strategy"] == "conservative_multi"]

        return {
            "total_trades":    len(self.trades),
            "winning_trades":  len(wins),
            "losing_trades":   len(losses),
            "win_rate":        round(len(wins) / len(self.trades), 3) if self.trades else 0,
            "total_pnl":       round(sum(pnls), 2),
            "avg_win":         round(sum(wins) / len(wins), 2) if wins else 0,
            "avg_loss":        round(sum(losses) / len(losses), 2) if losses else 0,
            "max_drawdown":    round(-max_dd, 2),
            "strategy_a_pnl":  round(sum(t["pnl"] for t in a_trades), 2),
            "strategy_b_pnl":  round(sum(t["pnl"] for t in b_trades), 2),
            "strategy_a_trades": len(a_trades),
            "strategy_b_trades": len(b_trades),
        }


# ---------------------------------------------------------------------------
# Push results to Supabase
# ---------------------------------------------------------------------------

def push_results(db: SupabaseDB, engine: BacktestEngine, summary: dict, cfg, start: date, end: date) -> str:
    config_snapshot = {
        "rsi_oversold":          cfg.rsi_oversold,
        "volume_ratio_threshold": cfg.volume_ratio_threshold,
        "max_per_trade_usd":     cfg.max_per_trade_usd,
        "primary_min_score":     5,
        "power_hour_min_score":  6,
        "strategy_a_tp":         cfg.strategy_a.take_profit_pct,
        "strategy_a_sl":         cfg.strategy_a.stop_loss_pct,
        "strategy_a_partial":    cfg.strategy_a.partial_exit_pct,
        "strategy_b_tp":         cfg.strategy_b.take_profit_pct,
        "strategy_b_sl":         cfg.strategy_b.stop_loss_pct,
        "strategy_b_partial":    cfg.strategy_b.partial_exit_pct,
    }

    result = db._db.table("backtest_runs").insert({
        "start_date":       start.isoformat(),
        "end_date":         end.isoformat(),
        "config":           config_snapshot,
        "total_trades":     summary["total_trades"],
        "winning_trades":   summary["winning_trades"],
        "losing_trades":    summary["losing_trades"],
        "total_pnl":        summary["total_pnl"],
        "win_rate":         summary["win_rate"],
        "avg_win":          summary["avg_win"],
        "avg_loss":         summary["avg_loss"],
        "max_drawdown":     summary["max_drawdown"],
        "strategy_a_pnl":   summary["strategy_a_pnl"],
        "strategy_b_pnl":   summary["strategy_b_pnl"],
        "strategy_a_trades": summary["strategy_a_trades"],
        "strategy_b_trades": summary["strategy_b_trades"],
    }).execute()

    run_id = result.data[0]["id"]
    logger.info("Backtest run saved: id=%s", run_id)

    # Trades
    if engine.trades:
        db._db.table("backtest_trades").insert([{
            "run_id":          run_id,
            "strategy":        t["strategy"],
            "ticker":          t["ticker"],
            "entry_date":      t["entry_date"].isoformat(),
            "entry_price":     t["entry_price"],
            "exit_price":      t["exit_price"],
            "shares":          t["shares"],
            "pnl":             t["pnl"],
            "exit_reason":     t["exit_reason"],
            "conviction_score": t["conviction_score"],
            "regime":          t["regime"],
        } for t in engine.trades]).execute()

    # Equity curve
    cumulative = 0.0
    equity_rows = []
    for d in sorted(engine.daily_pnl):
        cumulative += engine.daily_pnl[d]
        equity_rows.append({
            "run_id":         run_id,
            "date":           d.isoformat(),
            "daily_pnl":      engine.daily_pnl[d],
            "cumulative_pnl": round(cumulative, 2),
        })
    if equity_rows:
        db._db.table("backtest_equity").insert(equity_rows).execute()

    logger.info("Results pushed to Supabase ✓  run_id=%s", run_id)
    return run_id


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI Trading Bot — Backtester")
    parser.add_argument("--months", type=int, default=3, help="Months to backtest (default 3)")
    parser.add_argument("--start",  type=str, help="Start date YYYY-MM-DD")
    parser.add_argument("--end",    type=str, help="End date YYYY-MM-DD (default today)")
    args = parser.parse_args()

    end_date   = date.fromisoformat(args.end)   if args.end   else date.today()
    start_date = date.fromisoformat(args.start) if args.start else end_date - timedelta(days=30 * args.months)

    logger.info("=== Backtest: %s → %s ===", start_date, end_date)

    cfg         = load_config()
    data_client = MarketDataClient(cfg.alpaca_api_key, cfg.alpaca_secret_key)
    db          = SupabaseDB(cfg)

    engine  = BacktestEngine(data_client, cfg, start_date, end_date)
    summary = engine.run()

    logger.info("=== RESULTS ===")
    for k, v in summary.items():
        logger.info("  %-25s %s", k, v)

    run_id = push_results(db, engine, summary, cfg, start_date, end_date)
    logger.info("Open the dashboard Backtest tab to view results (run=%s)", run_id)
