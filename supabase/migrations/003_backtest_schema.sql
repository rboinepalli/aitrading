-- Migration 003 — Backtesting tables
--
-- Three tables written by bot/backtest.py:
--   backtest_runs    — one row per backtest run (summary + config snapshot)
--   backtest_trades  — individual simulated trades for each run
--   backtest_equity  — daily P&L + cumulative equity curve for each run
--
-- Run this in the Supabase SQL editor before running backtest.py for the first time.

-- ─────────────────────────────────────────────
-- backtest_runs — summary of a single backtest
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS backtest_runs (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  created_at       TIMESTAMPTZ DEFAULT NOW(),
  start_date       DATE NOT NULL,
  end_date         DATE NOT NULL,

  -- Config snapshot (RSI threshold, TP/SL %, etc.) as JSON so we can
  -- compare results across different parameter settings
  config           JSONB NOT NULL DEFAULT '{}',

  -- Aggregate results
  total_trades     INT     NOT NULL DEFAULT 0,
  winning_trades   INT     NOT NULL DEFAULT 0,
  losing_trades    INT     NOT NULL DEFAULT 0,
  win_rate         DECIMAL(5,3),        -- e.g. 0.625 = 62.5%
  total_pnl        DECIMAL(12,2),
  avg_win          DECIMAL(10,2),
  avg_loss         DECIMAL(10,2),
  max_drawdown     DECIMAL(10,2),

  -- Per-strategy breakdown
  strategy_a_pnl   DECIMAL(12,2),
  strategy_b_pnl   DECIMAL(12,2),
  strategy_a_trades INT,
  strategy_b_trades INT
);

-- Public read (dashboard can query without auth)
ALTER TABLE backtest_runs ENABLE ROW LEVEL SECURITY;
CREATE POLICY "public read backtest_runs"
  ON backtest_runs FOR SELECT USING (true);


-- ────────────────────────────────────────────────────────────
-- backtest_trades — every simulated trade from a backtest run
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS backtest_trades (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id           UUID NOT NULL REFERENCES backtest_runs(id) ON DELETE CASCADE,
  strategy         TEXT NOT NULL,   -- aggressive_3x | conservative_multi
  ticker           TEXT NOT NULL,
  entry_date       DATE NOT NULL,
  entry_price      DECIMAL(10,4) NOT NULL,
  exit_price       DECIMAL(10,4) NOT NULL,
  shares           INT  NOT NULL,
  pnl              DECIMAL(10,2),
  exit_reason      TEXT,            -- TAKE_PROFIT | PARTIAL_PROFIT | STOP_LOSS | EOD_CLOSE
  conviction_score INT,
  regime           TEXT             -- BULL | BEAR
);

ALTER TABLE backtest_trades ENABLE ROW LEVEL SECURITY;
CREATE POLICY "public read backtest_trades"
  ON backtest_trades FOR SELECT USING (true);

-- Index for fast filtering by run
CREATE INDEX IF NOT EXISTS idx_backtest_trades_run_id ON backtest_trades(run_id);


-- ─────────────────────────────────────────────────────────────────────────
-- backtest_equity — daily P&L + cumulative equity curve for one backtest run
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS backtest_equity (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id          UUID NOT NULL REFERENCES backtest_runs(id) ON DELETE CASCADE,
  date            DATE NOT NULL,
  daily_pnl       DECIMAL(10,2),
  cumulative_pnl  DECIMAL(12,2)
);

ALTER TABLE backtest_equity ENABLE ROW LEVEL SECURITY;
CREATE POLICY "public read backtest_equity"
  ON backtest_equity FOR SELECT USING (true);

CREATE INDEX IF NOT EXISTS idx_backtest_equity_run_id ON backtest_equity(run_id);
CREATE INDEX IF NOT EXISTS idx_backtest_equity_date   ON backtest_equity(run_id, date);
