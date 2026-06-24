import { useQuery } from '@tanstack/react-query'
import { supabase } from '../lib/supabase'

export interface Scan {
  id: string
  scanned_at: string
  ticker: string
  score: number | null
  rsi: number | null
  volume_ratio: number | null
  price_at_scan: number | null
  ema9_above: boolean | null
  ema20_above: boolean | null
  vwap_above: boolean | null
  catalyst_found: boolean | null
  catalyst_text: string | null
  sector_etf: string | null
  sector_etf_green: boolean | null
}

async function fetchScans(): Promise<Scan[]> {
  const { data, error } = await supabase
    .from('scans')
    .select('*')
    .order('scanned_at', { ascending: false })
    .limit(50)
  if (error) throw new Error(error.message)
  return data as Scan[]
}

export function useScans() {
  return useQuery({ queryKey: ['scans'], queryFn: fetchScans, staleTime: 60_000, refetchInterval: 60_000 })
}
