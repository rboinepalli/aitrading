-- =============================================================================
-- Migration 002: v2 schema — dual strategy + conviction scoring
-- =============================================================================
-- Run this in Supabase SQL Editor AFTER 001_initial_schema.sql
-- =============================================================================

-- ---------------------------------------------------------------------------
-- TRADES — add strategy and conviction tracking
-- ---------------------------------------------------------------------------
ALTER TABLE trades ADD COLUMN IF NOT EXISTS strategy          TEXT    DEFAULT 'aggressive_3x';
ALTER TABLE trades ADD COLUMN IF NOT EXISTS conviction_score  INT;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS signals_triggered TEXT[]; -- e.g. ARRAY['RSI','MACD','VWAP']
ALTER TABLE trades ADD COLUMN IF NOT EXISTS status            TEXT    DEFAULT 'OPEN';     -- OPEN / CLOSED_GAIN / CLOSED_LOSS
ALTER TABLE trades ADD COLUMN IF NOT EXISTS partial_exit_triggered BOOLEAN DEFAULT FALSE; -- did we already sell 50%?
ALTER TABLE trades ADD COLUMN IF NOT EXISTS stop_price        DECIMAL(10,4);              -- moves to breakeven after partial

-- ---------------------------------------------------------------------------
-- SIGNALS — add strategy and new indicator values
-- ---------------------------------------------------------------------------
ALTER TABLE signals ADD COLUMN IF NOT EXISTS strategy        TEXT;
ALTER TABLE signals ADD COLUMN IF NOT EXISTS macd            DECIMAL(10,6);  -- MACD line value
ALTER TABLE signals ADD COLUMN IF NOT EXISTS vwap            DECIMAL(10,4);  -- intraday VWAP
ALTER TABLE signals ADD COLUMN IF NOT EXISTS volume_ratio    DECIMAL(5,2);   -- current vol / 20-bar avg vol
ALTER TABLE signals ADD COLUMN IF NOT EXISTS conviction_score INT;            -- 0–8

-- ---------------------------------------------------------------------------
-- DAILY_SUMMARY — split P&L per strategy
-- ---------------------------------------------------------------------------
ALTER TABLE daily_summary ADD COLUMN IF NOT EXISTS strategy_a_pnl      DECIMAL(10,2) DEFAULT 0;
ALTER TABLE daily_summary ADD COLUMN IF NOT EXISTS strategy_b_pnl      DECIMAL(10,2) DEFAULT 0;
ALTER TABLE daily_summary ADD COLUMN IF NOT EXISTS strategy_a_trades    INT           DEFAULT 0;
ALTER TABLE daily_summary ADD COLUMN IF NOT EXISTS strategy_b_trades    INT           DEFAULT 0;

-- ---------------------------------------------------------------------------
-- BOT_EVENTS — audit log for regime changes, skipped trades, errors
-- ---------------------------------------------------------------------------
-- Every significant bot decision is written here so the dashboard can show
-- "why did the bot sit out today?" without needing to read raw logs.
CREATE TABLE IF NOT EXISTS bot_events (
  id         UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  timestamp  TIMESTAMPTZ DEFAULT NOW(),
  event_type TEXT,    -- STARTED / REGIME_CHANGE / SKIPPED_TRADE / DAILY_LIMIT_HIT / ERROR
  strategy   TEXT,    -- aggressive_3x / conservative_multi / NULL for system-wide events
  message    TEXT     -- human-readable explanation shown in dashboard
);

ALTER TABLE bot_events ENABLE ROW LEVEL SECURITY;
CREATE POLICY "public read bot_events" ON bot_events FOR SELECT USING (true);
