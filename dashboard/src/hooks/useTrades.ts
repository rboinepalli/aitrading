/**
 * hooks/useTrades.ts — Real-time subscription to the trades table.
 *
 * Supabase supports real-time updates over WebSockets — when the Python bot
 * inserts or updates a row in the trades table, this hook receives the change
 * and React re-renders the component automatically.
 *
 * useQuery (from TanStack Query) handles:
 *   - Initial data fetch
 *   - Background refetching
 *   - Loading/error states
 *
 * The Supabase channel subscription handles real-time push updates.
 */

import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { supabase } from '../lib/supabase'

// TypeScript interface matching the trades table schema.
// Nullable fields (exit_*, pnl) are null while the trade is open.
export interface Trade {
  id: string
  ticker: string
  entry_price: number
  exit_price: number | null
  shares: number
  entry_time: string       // ISO 8601 datetime string
  exit_time: string | null
  exit_reason: string | null  // TAKE_PROFIT | STOP_LOSS | EOD_CLOSE
  pnl: number | null
  regime: string           // BULL | BEAR | CHOPPY
  created_at: string
}

async function fetchTrades(): Promise<Trade[]> {
  const { data, error } = await supabase
    .from('trades')
    .select('*')
    .order('created_at', { ascending: false })  // newest first
    .limit(100)

  if (error) throw new Error(error.message)
  return data as Trade[]
}

export function useTrades() {
  const queryClient = useQueryClient()

  // TanStack Query: fetches trades and caches them under the key ['trades'].
  // staleTime: data is considered fresh for 30s before background refetch.
  const query = useQuery({
    queryKey: ['trades'],
    queryFn: fetchTrades,
    staleTime: 30_000,
  })

  // Subscribe to real-time changes on the trades table.
  // This runs once on mount (empty deps array = like componentDidMount).
  useEffect(() => {
    const channel = supabase
      .channel('trades-changes')
      .on(
        'postgres_changes',
        { event: '*', schema: 'public', table: 'trades' },
        () => {
          // When any row changes, invalidate the cache → triggers a refetch.
          // This is the React Query pattern for real-time invalidation.
          queryClient.invalidateQueries({ queryKey: ['trades'] })
        }
      )
      .subscribe()

    // Cleanup: unsubscribe when the component unmounts.
    // Equivalent to clearing a setInterval in React.
    return () => { supabase.removeChannel(channel) }
  }, [queryClient])

  return query
}
