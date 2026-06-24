import { useDailySummary } from '../hooks/useDailySummary'

export function DailySummary() {
  const { data: rows, isLoading } = useDailySummary()
  const today = rows?.[0]

  const winRate = today && today.trades_taken > 0
    ? Math.round((today.trades_won / today.trades_taken) * 100)
    : null

  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
      <Stat
        label="Today's P&L"
        value={today ? `${today.total_pnl >= 0 ? '+' : ''}$${today.total_pnl.toFixed(2)}` : '—'}
        positive={today ? today.total_pnl >= 0 : null}
        loading={isLoading}
      />
      <Stat
        label="Trades Today"
        value={today ? `${today.trades_taken}` : '—'}
        loading={isLoading}
      />
      <Stat
        label="Win Rate"
        value={winRate !== null ? `${winRate}%` : '—'}
        sub={today ? `${today.trades_won}W / ${today.trades_lost}L` : undefined}
        loading={isLoading}
      />
      <Stat
        label="Best / Worst"
        value={today?.best_ticker ?? '—'}
        sub={today?.worst_ticker ? `worst: ${today.worst_ticker}` : undefined}
        loading={isLoading}
      />
    </div>
  )
}

function Stat({
  label, value, sub, positive, loading
}: {
  label: string; value: string; sub?: string; positive?: boolean | null; loading: boolean
}) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white shadow-sm p-5">
      <p className="text-xs text-gray-400 uppercase tracking-wide mb-1">{label}</p>
      <p className={`text-2xl font-bold ${
        loading ? 'text-gray-300' :
        positive === true ? 'text-green-600' :
        positive === false ? 'text-red-600' : 'text-gray-900'
      }`}>
        {loading ? '...' : value}
      </p>
      {sub && <p className="text-xs text-gray-400 mt-1">{sub}</p>}
    </div>
  )
}
