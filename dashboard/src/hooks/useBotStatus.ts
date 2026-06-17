/**
 * hooks/useBotStatus.ts — Latest bot event + regime from bot_events table.
 * Powers the status pill and regime badge in the header.
 */

import { useQuery } from '@tanstack/react-query'
import { supabase } from '../lib/supabase'

export interface BotEvent {
  id: string
  timestamp: string
  event_type: string
  strategy: string | null
  message: string
}

async function fetchLatestEvent(): Promise<BotEvent | null> {
  const { data, error } = await supabase
    .from('bot_events')
    .select('*')
    .order('timestamp', { ascending: false })
    .limit(1)
    .maybeSingle()
  if (error) throw new Error(error.message)
  return data as BotEvent | null
}

export function useBotStatus() {
  return useQuery({
    queryKey: ['bot-status'],
    queryFn: fetchLatestEvent,
    refetchInterval: 60_000,  // refresh every minute
    staleTime: 30_000,
  })
}
