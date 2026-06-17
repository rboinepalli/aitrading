/**
 * hooks/usePosition.ts — Live open position from the trades table.
 *
 * Finds any trade row where exit_time IS NULL — that's the open position.
 * We derive this from Supabase rather than calling Alpaca directly from the
 * browser (we don't want Alpaca API keys in the frontend).
 *
 * Polls every 30 seconds for updates (combined with real-time subscription
 * in useTrades, the UI stays fresh without hammering the DB).
 */

import { useQuery } from '@tanstack/react-query'
import { supabase } from '../lib/supabase'
import type { Trade } from './useTrades'

async function fetchOpenPosition(): Promise<Trade | null> {
  const { data, error } = await supabase
    .from('trades')
    .select('*')
    .is('exit_time', null)   // exit_time IS NULL = position is open
    .limit(1)
    .maybeSingle()           // returns null instead of throwing if no rows

  if (error) throw new Error(error.message)
  return data as Trade | null
}

export function usePosition() {
  return useQuery({
    queryKey: ['open-position'],
    queryFn: fetchOpenPosition,
    // Refresh every 30 seconds to pick up unrealized P&L changes.
    // The bot updates the trade row on exit, so real-time will catch closes.
    refetchInterval: 30_000,
    staleTime: 15_000,
  })
}
