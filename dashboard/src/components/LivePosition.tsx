/**
 * LivePosition.tsx — Shows the currently open trade (if any).
 *
 * Reads from the `trades` table row where exit_time IS NULL.
 * Color-codes P&L green/red for instant visual feedback.
 *
 * Note: unrealized P&L shown here is based on the entry_price stored
 * at open. The actual current value would need a live price feed.
 * For v1 this is "P&L at last bot check" — accurate enough for monitoring.
 */

import { usePosition } from '../hooks/usePosition'
import { format } from 'date-fns'

// Badge colors by exit reason — not needed here but useful reference for TradeLog
const REGIME_COLORS: Record<string, string> = {
  BULL: 'bg-green-100 text-green-800',
  BEAR: 'bg-red-100 text-red-800',
  CHOPPY: 'bg-yellow-100 text-yellow-800',
}

export function LivePosition() {
  const { data: position, isLoading, isError } = usePosition()

  if (isLoading) {
    return (
      <div className="rounded-xl border border-gray-200 p-6 bg-white shadow-sm">
        <h2 className="text-lg font-semibold text-gray-700 mb-4">Live Position</h2>
        <p className="text-gray-400 text-sm">Loading...</p>
      </div>
    )
  }

  if (isError) {
    return (
      <div className="rounded-xl border border-red-200 p-6 bg-white shadow-sm">
        <h2 className="text-lg font-semibold text-gray-700 mb-4">Live Position</h2>
        <p className="text-red-500 text-sm">Failed to load position data.</p>
      </div>
    )
  }

  if (!position) {
    return (
      <div className="rounded-xl border border-gray-200 p-6 bg-white shadow-sm">
        <h2 className="text-lg font-semibold text-gray-700 mb-4">Live Position</h2>
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-gray-300" />
          <p className="text-gray-500 text-sm">No open position — bot is flat.</p>
        </div>
      </div>
    )
  }

  const entryValue = position.entry_price * position.shares
  const entryTime = format(new Date(position.entry_time), 'MMM d, h:mm a')
  const regimeClass = REGIME_COLORS[position.regime] ?? 'bg-gray-100 text-gray-700'

  return (
    <div className="rounded-xl border border-gray-200 p-6 bg-white shadow-sm">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold text-gray-700">Live Position</h2>
        {/* Green pulse indicator = position is open */}
        <span className="flex items-center gap-1.5 text-sm text-green-600 font-medium">
          <span className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
          OPEN
        </span>
      </div>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        {/* Ticker + regime */}
        <div>
          <p className="text-xs text-gray-400 uppercase tracking-wide">Ticker</p>
          <p className="text-2xl font-bold text-gray-900 mt-1">{position.ticker}</p>
          <span className={`inline-block mt-1 text-xs px-2 py-0.5 rounded-full font-medium ${regimeClass}`}>
            {position.regime}
          </span>
        </div>

        {/* Shares + entry price */}
        <div>
          <p className="text-xs text-gray-400 uppercase tracking-wide">Entry</p>
          <p className="text-xl font-semibold text-gray-900 mt-1">
            ${position.entry_price.toFixed(2)}
          </p>
          <p className="text-xs text-gray-500">{position.shares} shares</p>
        </div>

        {/* Exposure */}
        <div>
          <p className="text-xs text-gray-400 uppercase tracking-wide">Exposure</p>
          <p className="text-xl font-semibold text-gray-900 mt-1">
            ${entryValue.toFixed(0)}
          </p>
          <p className="text-xs text-gray-500">at entry</p>
        </div>

        {/* Entry time */}
        <div>
          <p className="text-xs text-gray-400 uppercase tracking-wide">Entered</p>
          <p className="text-sm font-medium text-gray-700 mt-1">{entryTime}</p>
        </div>
      </div>
    </div>
  )
}
