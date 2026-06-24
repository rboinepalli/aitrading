import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
import { supabase } from '../lib/supabase'

export interface BotState {
  daily_loss: number
  positions_open: number
  trading_halted: boolean
  halt_reason: string
}

async function fetchBotState(): Promise<BotState> {
  const { data, error } = await supabase.from('bot_state').select('key, value')
  if (error) throw new Error(error.message)
  const map: Record<string, string> = {}
  for (const row of data ?? []) map[row.key] = row.value
  return {
    daily_loss:      parseFloat(map['daily_loss'] ?? '0'),
    positions_open:  parseInt(map['positions_open'] ?? '0'),
    trading_halted:  map['trading_halted'] === 'true',
    halt_reason:     map['halt_reason'] ?? '',
  }
}

export function useBotState() {
  const queryClient = useQueryClient()
  const query = useQuery({
    queryKey: ['bot-state'],
    queryFn: fetchBotState,
    refetchInterval: 30_000,
  })
  useEffect(() => {
    const ch = supabase
      .channel('bot-state-changes')
      .on('postgres_changes', { event: '*', schema: 'public', table: 'bot_state' }, () => {
        queryClient.invalidateQueries({ queryKey: ['bot-state'] })
      })
      .subscribe()
    return () => { supabase.removeChannel(ch) }
  }, [queryClient])
  return query
}
