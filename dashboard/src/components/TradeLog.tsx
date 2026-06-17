/**
 * TradeLog.tsx — Filterable table of all trades (v2).
 * Adds strategy column and strategy filter dropdown.
 */

import { useState } from 'react'
import { useTrades, type Trade } from '../hooks/useTrades'
import { format } from 'date-fns'

const EXIT_LABELS: Record<string, { label: string; cls: string }> = {
  TAKE_PROFIT:    { label: 'Take Profit',    cls: 'bg-green-100 text-green-700' },
  PARTIAL_PROFIT: { label: 'Partial',        cls: 'bg-teal-100 text-teal-700' },
  STOP_LOSS:      { label: 'Stop Loss',      cls: 'bg-red-100 text-red-700' },
  EOD_CLOSE:      { label: 'EOD Close',      cls: 'bg-blue-100 text-blue-700' },
}

const STRATEGY_LABELS: Record<string, { label: string; cls: string }> = {
  aggressive_3x:      { label: 'A · 3x',    cls: 'bg-blue-100 text-blue-700' },
  conservative_multi: { label: 'B · Multi', cls: 'bg-purple-100 text-purple-700' },
}

function PnLCell({ pnl }: { pnl: number | null }) {
  if (pnl === null) return <span className="text-gray-400">—</span>
  return (
    <span className={`font-semibold tabular-nums ${pnl >= 0 ? 'text-green-600' : 'text-red-600'}`}>
      {pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}
    </span>
  )
}

function TradeRow({ trade }: { trade: Trade }) {
  const entryTime = format(new Date(trade.entry_time), 'MMM d, h:mm a')
  const exitReason = trade.exit_reason ? EXIT_LABELS[trade.exit_reason] : null
  const strategy = trade.strategy ? STRATEGY_LABELS[trade.strategy] : null

  return (
    <tr className="border-b border-gray-100 hover:bg-gray-50 transition-colors">
      <td className="py-3 px-4">
        {strategy && (
          <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${strategy.cls}`}>
            {strategy.label}
          </span>
        )}
      </td>
      <td className="py-3 px-4 font-medium text-gray-900">{trade.ticker}</td>
      <td className="py-3 px-4 tabular-nums text-sm text-gray-600">${trade.entry_price.toFixed(2)}</td>
      <td className="py-3 px-4 tabular-nums text-sm text-gray-600">
        {trade.exit_price ? `$${trade.exit_price.toFixed(2)}` : '—'}
      </td>
      <td className="py-3 px-4 text-sm text-gray-500 tabular-nums">{trade.shares}</td>
      <td className="py-3 px-4">
        <PnLCell pnl={trade.pnl} />
      </td>
      <td className="py-3 px-4 text-center text-sm font-semibold text-gray-700">
        {(trade as any).conviction_score ?? '—'}
      </td>
      <td className="py-3 px-4">
        {exitReason ? (
          <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${exitReason.cls}`}>
            {exitReason.label}
          </span>
        ) : (
          <span className="text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-500">OPEN</span>
        )}
      </td>
      <td className="py-3 px-4 text-xs text-gray-400">{entryTime}</td>
    </tr>
  )
}

export function TradeLog() {
  const { data: trades, isLoading, isError } = useTrades()
  const [filter, setFilter] = useState<'all' | 'aggressive_3x' | 'conservative_multi'>('all')

  const filtered = trades?.filter(t =>
    filter === 'all' || (t as any).strategy === filter
  ) ?? []

  return (
    <div className="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden">
      <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
        <h2 className="text-lg font-semibold text-gray-700">Trade Log</h2>
        <div className="flex items-center gap-3">
          <span className="text-xs text-gray-400">{filtered.length} trades</span>
          {/* Strategy filter */}
          <select
            value={filter}
            onChange={e => setFilter(e.target.value as typeof filter)}
            className="text-xs border border-gray-200 rounded-lg px-2 py-1 text-gray-600 bg-white"
          >
            <option value="all">All strategies</option>
            <option value="aggressive_3x">Strategy A (3x)</option>
            <option value="conservative_multi">Strategy B (Multi)</option>
          </select>
        </div>
      </div>

      {isLoading && <div className="px-6 py-8 text-center text-gray-400 text-sm">Loading trades...</div>}
      {isError && <div className="px-6 py-8 text-center text-red-500 text-sm">Failed to load trades.</div>}
      {!isLoading && filtered.length === 0 && (
        <div className="px-6 py-8 text-center text-gray-400 text-sm">
          No trades yet — the bot populates this during market hours.
        </div>
      )}

      {filtered.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50">
              <tr>
                {['Strategy', 'Ticker', 'Entry', 'Exit', 'Shares', 'P&L', 'Score', 'Reason', 'Time'].map(h => (
                  <th key={h} className="py-2 px-4 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.map(trade => <TradeRow key={trade.id} trade={trade} />)}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
