/**
 * StrategyCard.tsx — Shows live open position for one strategy.
 * Used twice in App.tsx — once for Strategy A, once for Strategy B.
 */

import { useQuery } from '@tanstack/react-query'
import { supabase } from '../lib/supabase'
import { format } from 'date-fns'
import type { Trade } from '../hooks/useTrades'

interface Props {
  strategyName: string        // "aggressive_3x" or "conservative_multi"
  displayName: string         // "Strategy A" or "Strategy B"
  description: string         // "TQQQ / SQQQ" or "QQQ / NVDA / AAPL..."
  accentColor: string         // tailwind color class prefix e.g. "blue" or "purple"
}

async function fetchOpenPosition(strategyName: string): Promise<Trade | null> {
  const { data, error } = await supabase
    .from('trades')
    .select('*')
    .eq('strategy', strategyName)
    .eq('status', 'OPEN')
    .limit(1)
    .maybeSingle()
  if (error) throw new Error(error.message)
  return data as Trade | null
}

export function StrategyCard({ strategyName, displayName, description, accentColor }: Props) {
  const { data: position, isLoading } = useQuery({
    queryKey: ['open-position', strategyName],
    queryFn: () => fetchOpenPosition(strategyName),
    refetchInterval: 30_000,
    staleTime: 15_000,
  })

  const borderClass = `border-${accentColor}-200`
  const dotClass = `bg-${accentColor}-500`
  const textClass = `text-${accentColor}-700`
  const badgeClass = `bg-${accentColor}-100 text-${accentColor}-700`

  return (
    <div className={`rounded-xl border ${borderClass} p-5 bg-white shadow-sm flex-1 min-w-[280px]`}>
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className={`text-sm font-bold ${textClass} uppercase tracking-wide`}>{displayName}</h3>
          <p className="text-xs text-gray-400 mt-0.5">{description}</p>
        </div>
        {/* Strategy name badge */}
        <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${badgeClass}`}>
          {strategyName === 'aggressive_3x' ? '3x' : 'Multi'}
        </span>
      </div>

      {isLoading && (
        <p className="text-xs text-gray-400">Loading...</p>
      )}

      {!isLoading && !position && (
        <div className="flex items-center gap-2 py-2">
          <span className="w-2 h-2 rounded-full bg-gray-300" />
          <p className="text-sm text-gray-500">No open position — flat</p>
        </div>
      )}

      {position && (
        <div className="space-y-3">
          {/* Open indicator */}
          <div className="flex items-center gap-1.5">
            <span className={`w-2 h-2 rounded-full ${dotClass} animate-pulse`} />
            <span className="text-xs font-semibold text-gray-600">OPEN</span>
            {position.partial_exit_triggered && (
              <span className="text-xs px-1.5 py-0.5 rounded bg-orange-100 text-orange-700 ml-1">
                50% sold
              </span>
            )}
          </div>

          {/* Main stats grid */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <p className="text-xs text-gray-400">Ticker</p>
              <p className="text-xl font-bold text-gray-900">{position.ticker}</p>
            </div>
            <div>
              <p className="text-xs text-gray-400">Entry</p>
              <p className="text-lg font-semibold text-gray-900">
                ${position.entry_price.toFixed(2)}
              </p>
              <p className="text-xs text-gray-400">{position.shares} shares</p>
            </div>
            <div>
              <p className="text-xs text-gray-400">Conviction</p>
              <p className="text-lg font-semibold text-gray-900">
                {position.conviction_score ?? '—'}<span className="text-sm text-gray-400">/8</span>
              </p>
            </div>
            <div>
              <p className="text-xs text-gray-400">Entered</p>
              <p className="text-sm text-gray-600">
                {format(new Date(position.entry_time), 'h:mm a')}
              </p>
            </div>
          </div>

          {/* Signals fired */}
          {position.signals_triggered && position.signals_triggered.length > 0 && (
            <div className="flex flex-wrap gap-1 pt-1">
              {position.signals_triggered.map((sig: string) => (
                <span key={sig} className="text-xs px-1.5 py-0.5 rounded bg-green-50 text-green-700 font-medium">
                  ✓{sig}
                </span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
