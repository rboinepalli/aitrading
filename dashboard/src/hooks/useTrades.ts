import { useEffect } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { supabase } from '../lib/supabase'

export interface Trade {
  id: string
  ticker: string
  phase: string
  entry_price: number
  stop_loss: number | null
  target: number | null
  shares: number
  entry_time: string
  exit_time: string | null
  exit_price: number | null
  exit_reason: string | null
  pnl_dollars: number | null
  pnl_percent: number | null
  hold_hours: number | null
}

async function fetchTrades(): Promise<Trade[]> {
  const { data, error } = await supabase
    .from('trades')
    .select('*')
    .order('entry_time', { ascending: false })
    .limit(100)
  if (error) throw new Error(error.message)
  return data as Trade[]
}

export function useTrades() {
  const queryClient = useQueryClient()
  const query = useQuery({ queryKey: ['trades'], queryFn: fetchTrades, staleTime: 30_000 })
  useEffect(() => {
    const ch = supabase
      .channel('trades-changes')
      .on('postgres_changes', { event: '*', schema: 'public', table: 'trades' }, () => {
        queryClient.invalidateQueries({ queryKey: ['trades'] })
      })
      .subscribe()
    return () => { supabase.removeChannel(ch) }
  }, [queryClient])
  return query
}
