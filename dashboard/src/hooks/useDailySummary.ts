import { useQuery } from '@tanstack/react-query'
import { supabase } from '../lib/supabase'

export interface DailySummary {
  date: string
  trades_taken: number
  trades_won: number
  trades_lost: number
  total_pnl: number
  avg_hold_hrs: number | null
  best_ticker: string | null
  worst_ticker: string | null
}

async function fetchSummaries(): Promise<DailySummary[]> {
  const { data, error } = await supabase
    .from('daily_summary')
    .select('*')
    .order('date', { ascending: false })
    .limit(30)
  if (error) throw new Error(error.message)
  return data as DailySummary[]
}

export function useDailySummary() {
  return useQuery({ queryKey: ['daily-summary'], queryFn: fetchSummaries, staleTime: 60_000 })
}
