-- =============================================================================
-- 004_momentum_scanner.sql — Momentum Scanner schema
-- Replaces the v2/v3 multi-strategy schema with a cleaner 4-table design.
-- Run in Supabase SQL editor.
-- =============================================================================

-- 1. Every scan result — even stocks not traded (backtesting source of truth)
CREATE TABLE IF NOT EXISTS scans (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  scanned_at        timestamptz DEFAULT now(),
  ticker            text NOT NULL,
  score             int,
  rsi               numeric,
  volume_ratio      numeric,
  price_at_scan     numeric,
  ema9_above        bool,
  ema20_above       bool,
  vwap_above        bool,
  catalyst_found    bool,
  catalyst_text     text,
  sector_etf        text,
  sector_etf_green  bool,
  price_1day_later  numeric,   -- filled by EOD job next trading day
  price_2days_later numeric    -- filled by EOD job 2 trading days later
);

-- 2. Every approved trade — full lifecycle from entry to exit
CREATE TABLE IF NOT EXISTS trades (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  scan_id      uuid REFERENCES scans(id),
  ticker       text NOT NULL,
  phase        text DEFAULT 'paper',   -- 'paper' or 'live'
  entry_price  numeric,
  stop_loss    numeric,
  target       numeric,
  shares       int,
  entry_time   timestamptz,
  exit_time    timestamptz,
  exit_price   numeric,
  exit_reason  text,   -- 'target_hit' | 'stop_hit' | 'rsi_exit' | 'spy_circuit' | 'force_eod'
  pnl_dollars  numeric,
  pnl_percent  numeric,
  hold_hours   numeric
);

-- 3. Daily summary — written by EOD job each trading day
CREATE TABLE IF NOT EXISTS daily_summary (
  date          date PRIMARY KEY,
  trades_taken  int DEFAULT 0,
  trades_won    int DEFAULT 0,
  trades_lost   int DEFAULT 0,
  total_pnl     numeric DEFAULT 0,
  avg_hold_hrs  numeric,
  best_ticker   text,
  worst_ticker  text
);

-- 4. Bot state — key/value store that survives restarts and redeployments
CREATE TABLE IF NOT EXISTS bot_state (
  key        text PRIMARY KEY,
  value      text,
  updated_at timestamptz DEFAULT now()
);

-- Seed default bot_state rows
INSERT INTO bot_state (key, value) VALUES
  ('daily_loss',      '0'),
  ('positions_open',  '0'),
  ('trading_halted',  'false'),
  ('halt_reason',     '')
ON CONFLICT (key) DO NOTHING;

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_scans_scanned_at  ON scans (scanned_at DESC);
CREATE INDEX IF NOT EXISTS idx_scans_ticker       ON scans (ticker);
CREATE INDEX IF NOT EXISTS idx_trades_ticker      ON trades (ticker);
CREATE INDEX IF NOT EXISTS idx_trades_exit_time   ON trades (exit_time);
CREATE INDEX IF NOT EXISTS idx_trades_open        ON trades (exit_time) WHERE exit_time IS NULL;
