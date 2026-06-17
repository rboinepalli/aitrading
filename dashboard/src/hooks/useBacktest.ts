/**
 * hooks/useBacktest.ts — Fetches backtest results from Supabase.
 *
 * Three queries, all one-time fetches (no real-time subscription needed —
 * backtests are run manually and don't change after being pushed):
 *
 *  useBacktestRuns()        — list of all runs (most recent first)
 *  useBacktestTrades(runId) — simulated trades for a specific run
 *  useBacktestEquity(runId) — daily equity curve for a specific run
 */

import { useQuery } from '@tanstack/react-query'
import { supabase } from '../lib/supabase'

// ─── Types (mirror bot/backtest.py _record() and push_results()) ─────────────

export interface BacktestRun {
  id: string
  created_at: string
  start_date: string
  end_date: string
  config: Record<string, number>
  total_trades: number
  winning_trades: number
  losing_trades: number
  win_rate: number
  total_pnl: number
  avg_win: number
  avg_loss: number
  max_drawdown: number
  strategy_a_pnl: number
  strategy_b_pnl: number
  strategy_a_trades: number
  strategy_b_trades: number
}

export interface BacktestTrade {
  id: string
  run_id: string
  strategy: string
  ticker: string
  entry_date: string
  entry_price: number
  exit_price: number
  shares: number
  pnl: number
  exit_reason: string
  conviction_score: number
  regime: string
}

export interface BacktestEquityPoint {
  id: string
  run_id: string
  date: string
  daily_pnl: number
  cumulative_pnl: number
}

// ─── Queries ──────────────────────────────────────────────────────────────────

async function fetchRuns(): Promise<BacktestRun[]> {
  const { data, error } = await supabase
    .from('backtest_runs')
    .select('*')
    .order('created_at', { ascending: false })
    .limit(20)
  if (error) throw new Error(error.message)
  return data as BacktestRun[]
}

async function fetchTrades(runId: string): Promise<BacktestTrade[]> {
  const { data, error } = await supabase
    .from('backtest_trades')
    .select('*')
    .eq('run_id', runId)
    .order('entry_date', { ascending: true })
  if (error) throw new Error(error.message)
  return data as BacktestTrade[]
}

async function fetchEquity(runId: string): Promise<BacktestEquityPoint[]> {
  const { data, error } = await supabase
    .from('backtest_equity')
    .select('*')
    .eq('run_id', runId)
    .order('date', { ascending: true })
  if (error) throw new Error(error.message)
  return data as BacktestEquityPoint[]
}

// ─── Hooks ────────────────────────────────────────────────────────────────────

export function useBacktestRuns() {
  return useQuery({
    queryKey: ['backtest_runs'],
    queryFn: fetchRuns,
    staleTime: 60_000, // backtest data rarely changes — 1 min is fine
  })
}

export function useBacktestTrades(runId: string | null) {
  return useQuery({
    queryKey: ['backtest_trades', runId],
    queryFn: () => fetchTrades(runId!),
    enabled: !!runId,
    staleTime: 60_000,
  })
}

export function useBacktestEquity(runId: string | null) {
  return useQuery({
    queryKey: ['backtest_equity', runId],
    queryFn: () => fetchEquity(runId!),
    enabled: !!runId,
    staleTime: 60_000,
  })
}
