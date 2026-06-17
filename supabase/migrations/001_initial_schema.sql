-- =============================================================================
-- Migration 001: Initial schema for the AI trading bot
-- =============================================================================
-- Run this in your Supabase SQL editor (or via `supabase db push` CLI).
--
-- Three tables:
--   trades        — every trade opened and closed by the bot
--   signals       — every signal evaluation (for debugging + audit)
--   daily_summary — one row per trading day, written at EOD
-- =============================================================================

-- ---------------------------------------------------------------------------
-- TRADES
-- ---------------------------------------------------------------------------
-- Tracks the lifecycle of every position the bot takes.
-- A row is inserted when we open a position, then updated when we close it.
-- exit_price / exit_time / pnl / exit_reason are NULL while the trade is open.
--
-- In TypeScript you'd model this as:
--   interface Trade { id: string; ticker: string; entryPrice: number; ... }
-- Python uses a plain dict or dataclass for the same idea.
-- ---------------------------------------------------------------------------
CREATE TABLE trades (
  id           UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
  ticker       TEXT         NOT NULL,       -- 'TQQQ' or 'SQQQ'
  entry_price  DECIMAL(10,4),               -- price per share at buy
  exit_price   DECIMAL(10,4),               -- price per share at sell (NULL if open)
  shares       INTEGER,                     -- number of shares purchased
  entry_time   TIMESTAMPTZ,                 -- when we entered the position
  exit_time    TIMESTAMPTZ,                 -- when we exited (NULL if open)
  exit_reason  TEXT,                        -- TAKE_PROFIT / STOP_LOSS / EOD_CLOSE
  pnl          DECIMAL(10,2),              -- realized profit/loss in dollars (NULL if open)
  regime       TEXT,                        -- BULL / BEAR / CHOPPY at entry time
  created_at   TIMESTAMPTZ  DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- SIGNALS
-- ---------------------------------------------------------------------------
-- Every time the bot evaluates whether to enter a trade, it logs a signal row.
-- This lets you replay decisions after the fact and tune your strategy.
-- Stored even when signal = 'NONE' so you can see why the bot sat out.
-- ---------------------------------------------------------------------------
CREATE TABLE signals (
  id         UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
  ticker     TEXT,                          -- which ETF was evaluated
  ts         TIMESTAMPTZ,                   -- when the signal was generated
  regime     TEXT,                          -- BULL / BEAR / CHOPPY at that moment
  rsi        DECIMAL(6,2),                  -- RSI value (14-period by default)
  ema_fast   DECIMAL(10,4),                 -- fast EMA value (9-period by default)
  ema_slow   DECIMAL(10,4),                 -- slow EMA value (21-period by default)
  vix        DECIMAL(6,2),                  -- VIX at signal time
  signal     TEXT,                          -- 'BUY' or 'NONE'
  created_at TIMESTAMPTZ  DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- DAILY_SUMMARY
-- ---------------------------------------------------------------------------
-- Written once per day at market close (~4pm ET).
-- One row per date — UNIQUE constraint enforces that.
-- Use this for the dashboard's daily P&L view.
-- ---------------------------------------------------------------------------
CREATE TABLE daily_summary (
  id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
  date            DATE         UNIQUE NOT NULL,  -- trading date (ET)
  total_pnl       DECIMAL(10,2),                 -- sum of all closed trade P&L for the day
  trades_taken    INTEGER,                        -- how many trades were executed
  winning_trades  INTEGER,                        -- trades with pnl > 0
  losing_trades   INTEGER,                        -- trades with pnl <= 0
  max_drawdown    DECIMAL(10,2),                  -- worst intraday drawdown ($)
  regime_at_close TEXT,                           -- regime when market closed
  created_at      TIMESTAMPTZ  DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- ROW LEVEL SECURITY (RLS)
-- ---------------------------------------------------------------------------
-- Supabase exposes two keys:
--   anon key   → safe to use in the browser dashboard (read-only via RLS)
--   service key → used by the Python bot (bypasses RLS, full write access)
--
-- The policies below allow the anon key to SELECT all rows.
-- The Python bot uses the service key which bypasses RLS entirely.
-- ---------------------------------------------------------------------------
ALTER TABLE trades        ENABLE ROW LEVEL SECURITY;
ALTER TABLE signals       ENABLE ROW LEVEL SECURITY;
ALTER TABLE daily_summary ENABLE ROW LEVEL SECURITY;

-- Allow the React dashboard (anon/authenticated users) to read all rows
CREATE POLICY "public read trades"         ON trades        FOR SELECT USING (true);
CREATE POLICY "public read signals"        ON signals       FOR SELECT USING (true);
CREATE POLICY "public read daily_summary"  ON daily_summary FOR SELECT USING (true);
