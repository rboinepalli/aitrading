import { useTrades, type Trade } from '../hooks/useTrades'
import { format } from 'date-fns'

const EXIT_LABELS: Record<string, { label: string; cls: string }> = {
  target_hit:   { label: 'Target',    cls: 'bg-green-100 text-green-700' },
  stop_hit:     { label: 'Stop',      cls: 'bg-red-100 text-red-700' },
  rsi_exit:     { label: 'RSI',       cls: 'bg-yellow-100 text-yellow-700' },
  spy_circuit:  { label: 'Circuit',   cls: 'bg-orange-100 text-orange-700' },
  force_eod:    { label: 'EOD',       cls: 'bg-blue-100 text-blue-700' },
}

function PnL({ val }: { val: number | null }) {
  if (val === null) return <span className="text-gray-400">—</span>
  return (
    <span className={`font-semibold tabular-nums ${val >= 0 ? 'text-green-600' : 'text-red-600'}`}>
      {val >= 0 ? '+' : ''}${val.toFixed(2)}
    </span>
  )
}

function TradeRow({ t }: { t: Trade }) {
  const exit = t.exit_reason ? EXIT_LABELS[t.exit_reason] : null
  const isOpen = !t.exit_time
  return (
    <tr className="border-b border-gray-100 hover:bg-gray-50 transition-colors">
      <td className="py-3 px-4 font-bold text-gray-900">{t.ticker}</td>
      <td className="py-3 px-4 tabular-nums text-sm text-gray-600">${t.entry_price.toFixed(2)}</td>
      <td className="py-3 px-4 tabular-nums text-sm text-gray-500">
        {t.stop_loss ? `$${t.stop_loss.toFixed(2)}` : '—'}
      </td>
      <td className="py-3 px-4 tabular-nums text-sm text-gray-500">
        {t.target ? `$${t.target.toFixed(2)}` : '—'}
      </td>
      <td className="py-3 px-4 tabular-nums text-sm text-gray-600">
        {t.exit_price ? `$${t.exit_price.toFixed(2)}` : '—'}
      </td>
      <td className="py-3 px-4 text-sm text-gray-500">{t.shares}</td>
      <td className="py-3 px-4"><PnL val={t.pnl_dollars} /></td>
      <td className="py-3 px-4">
        {isOpen ? (
          <span className="text-xs px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-700 font-medium">OPEN</span>
        ) : exit ? (
          <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${exit.cls}`}>{exit.label}</span>
        ) : null}
      </td>
      <td className="py-3 px-4 text-xs text-gray-400">
        {format(new Date(t.entry_time), 'MMM d, h:mm a')}
      </td>
      <td className="py-3 px-4 text-xs text-gray-400">
        <span className={`px-1.5 py-0.5 rounded text-xs ${t.phase === 'live' ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'}`}>
          {t.phase}
        </span>
      </td>
    </tr>
  )
}

export function TradeLog() {
  const { data: trades, isLoading, isError } = useTrades()
  const open   = trades?.filter(t => !t.exit_time) ?? []
  const closed = trades?.filter(t =>  t.exit_time) ?? []
  const all    = [...open, ...closed]

  return (
    <div className="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden">
      <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
        <h2 className="text-lg font-semibold text-gray-700">Trade Log</h2>
        <div className="flex items-center gap-3 text-xs text-gray-400">
          <span>{open.length} open</span>
          <span>{closed.length} closed</span>
        </div>
      </div>

      {isLoading && <div className="px-6 py-8 text-center text-gray-400 text-sm">Loading trades...</div>}
      {isError   && <div className="px-6 py-8 text-center text-red-500 text-sm">Failed to load trades.</div>}
      {!isLoading && all.length === 0 && (
        <div className="px-6 py-8 text-center text-gray-400 text-sm">
          No trades yet — approve a scan pick via Telegram to start.
        </div>
      )}

      {all.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50">
              <tr>
                {['Ticker', 'Entry', 'Stop', 'Target', 'Exit', 'Shares', 'P&L', 'Reason', 'Time', 'Phase'].map(h => (
                  <th key={h} className="py-2 px-4 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {all.map(t => <TradeRow key={t.id} t={t} />)}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
