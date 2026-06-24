import { useScans, type Scan } from '../hooks/useScans'
import { format } from 'date-fns'

function Check({ val }: { val: boolean | null }) {
  if (val === null) return <span className="text-gray-300">—</span>
  return <span className={val ? 'text-green-500' : 'text-red-400'}>{val ? '✓' : '✗'}</span>
}

function ScoreBar({ score }: { score: number | null }) {
  if (score === null) return <span className="text-gray-400">—</span>
  const color = score >= 75 ? 'bg-green-500' : score >= 60 ? 'bg-yellow-400' : 'bg-red-400'
  return (
    <div className="flex items-center gap-2">
      <div className="w-16 h-1.5 bg-gray-100 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${score}%` }} />
      </div>
      <span className="tabular-nums text-sm font-medium text-gray-700">{score}</span>
    </div>
  )
}

function ScanRow({ s }: { s: Scan }) {
  return (
    <tr className="border-b border-gray-100 hover:bg-gray-50 transition-colors">
      <td className="py-2 px-4 font-bold text-gray-900">{s.ticker}</td>
      <td className="py-2 px-4"><ScoreBar score={s.score} /></td>
      <td className="py-2 px-4 tabular-nums text-sm text-gray-600">
        {s.price_at_scan ? `$${s.price_at_scan.toFixed(2)}` : '—'}
      </td>
      <td className="py-2 px-4 tabular-nums text-sm text-gray-500">
        {s.rsi ? s.rsi.toFixed(0) : '—'}
      </td>
      <td className="py-2 px-4 tabular-nums text-sm text-gray-500">
        {s.volume_ratio ? `${s.volume_ratio.toFixed(1)}x` : '—'}
      </td>
      <td className="py-2 px-4 text-center"><Check val={s.ema9_above} /></td>
      <td className="py-2 px-4 text-center"><Check val={s.vwap_above} /></td>
      <td className="py-2 px-4 text-center"><Check val={s.catalyst_found} /></td>
      <td className="py-2 px-4 text-center"><Check val={s.sector_etf_green} /></td>
      <td className="py-2 px-4 text-xs text-gray-400 max-w-[160px] truncate" title={s.catalyst_text ?? ''}>
        {s.catalyst_text ?? '—'}
      </td>
      <td className="py-2 px-4 text-xs text-gray-400">
        {format(new Date(s.scanned_at), 'MMM d, h:mm a')}
      </td>
    </tr>
  )
}

export function ScanLog() {
  const { data: scans, isLoading, isError } = useScans()

  return (
    <div className="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden">
      <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
        <h2 className="text-lg font-semibold text-gray-700">Scan Log</h2>
        <span className="text-xs text-gray-400">{scans?.length ?? 0} recent scans</span>
      </div>

      {isLoading && <div className="px-6 py-8 text-center text-gray-400 text-sm">Loading scans...</div>}
      {isError   && <div className="px-6 py-8 text-center text-red-500 text-sm">Failed to load scans.</div>}
      {!isLoading && (scans?.length ?? 0) === 0 && (
        <div className="px-6 py-8 text-center text-gray-400 text-sm">
          No scans yet — first scan runs at 9:15am ET on a market day.
        </div>
      )}

      {(scans?.length ?? 0) > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50">
              <tr>
                {['Ticker', 'Score', 'Price', 'RSI', 'Vol Ratio', 'EMA9↑', 'VWAP↑', 'Catalyst', 'Sector ETF↑', 'Headline', 'Time'].map(h => (
                  <th key={h} className="py-2 px-4 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {scans!.map(s => <ScanRow key={s.id} s={s} />)}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
