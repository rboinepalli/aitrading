/**
 * TradeLog.tsx — Table of all completed trades with P&L.
 *
 * Reads from the trades table, newest first.
 * Open trades (exit_time = null) appear at the top with a OPEN badge.
 * Closed trades show exit reason (TAKE_PROFIT, STOP_LOSS, EOD_CLOSE) and P&L.
 */

import { useTrades, type Trade } from '../hooks/useTrades'
import { format } from 'date-fns'

const EXIT_REASON_LABELS: Record<string, { label: string; class: string }> = {
  TAKE_PROFIT: { label: 'Take Profit', class: 'bg-green-100 text-green-700' },
  STOP_LOSS:   { label: 'Stop Loss',   class: 'bg-red-100 text-red-700' },
  EOD_CLOSE:   { label: 'EOD Close',   class: 'bg-blue-100 text-blue-700' },
}

const REGIME_DOT: Record<string, string> = {
  BULL: 'bg-green-400',
  BEAR: 'bg-red-400',
  CHOPPY: 'bg-yellow-400',
}

function PnLCell({ pnl }: { pnl: number | null }) {
  if (pnl === null) {
    return <span className="text-gray-400 text-sm">—</span>
  }
  const isPositive = pnl >= 0
  return (
    <span className={`font-semibold tabular-nums ${isPositive ? 'text-green-600' : 'text-red-600'}`}>
      {isPositive ? '+' : ''}${pnl.toFixed(2)}
    </span>
  )
}

function ExitReasonBadge({ reason }: { reason: string | null }) {
  if (!reason) {
    return (
      <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-500">
        OPEN
      </span>
    )
  }
  const { label, class: cls } = EXIT_REASON_LABELS[reason] ?? {
    label: reason,
    class: 'bg-gray-100 text-gray-600',
  }
  return (
    <span className={`inline-block text-xs px-2 py-0.5 rounded-full font-medium ${cls}`}>
      {label}
    </span>
  )
}

function TradeRow({ trade }: { trade: Trade }) {
  const entryTime = format(new Date(trade.entry_time), 'MMM d, h:mm a')
  const exitTime = trade.exit_time ? format(new Date(trade.exit_time), 'h:mm a') : null
  const dotClass = REGIME_DOT[trade.regime] ?? 'bg-gray-400'

  return (
    <tr className="border-b border-gray-100 hover:bg-gray-50 transition-colors">
      <td className="py-3 px-4">
        <div className="flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full ${dotClass}`} title={trade.regime} />
          <span className="font-medium text-gray-900">{trade.ticker}</span>
        </div>
      </td>
      <td className="py-3 px-4 text-sm text-gray-600 tabular-nums">
        ${trade.entry_price.toFixed(2)}
      </td>
      <td className="py-3 px-4 text-sm text-gray-600 tabular-nums">
        {trade.exit_price ? `$${trade.exit_price.toFixed(2)}` : '—'}
      </td>
      <td className="py-3 px-4 text-sm text-gray-500 tabular-nums">{trade.shares}</td>
      <td className="py-3 px-4">
        <PnLCell pnl={trade.pnl} />
      </td>
      <td className="py-3 px-4">
        <ExitReasonBadge reason={trade.exit_reason} />
      </td>
      <td className="py-3 px-4 text-sm text-gray-400">
        {entryTime}{exitTime ? ` → ${exitTime}` : ''}
      </td>
    </tr>
  )
}

export function TradeLog() {
  const { data: trades, isLoading, isError } = useTrades()

  return (
    <div className="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden">
      <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
        <h2 className="text-lg font-semibold text-gray-700">Trade Log</h2>
        {trades && (
          <span className="text-xs text-gray-400">{trades.length} trades</span>
        )}
      </div>

      {isLoading && (
        <div className="px-6 py-8 text-center text-gray-400 text-sm">Loading trades...</div>
      )}

      {isError && (
        <div className="px-6 py-8 text-center text-red-500 text-sm">
          Failed to load trades. Check Supabase connection.
        </div>
      )}

      {trades && trades.length === 0 && (
        <div className="px-6 py-8 text-center text-gray-400 text-sm">
          No trades yet — the bot will populate this when it runs.
        </div>
      )}

      {trades && trades.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50">
              <tr>
                <th className="py-2 px-4 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">Ticker</th>
                <th className="py-2 px-4 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">Entry</th>
                <th className="py-2 px-4 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">Exit</th>
                <th className="py-2 px-4 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">Shares</th>
                <th className="py-2 px-4 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">P&L</th>
                <th className="py-2 px-4 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">Reason</th>
                <th className="py-2 px-4 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">Time</th>
              </tr>
            </thead>
            <tbody>
              {trades.map(trade => (
                <TradeRow key={trade.id} trade={trade} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
