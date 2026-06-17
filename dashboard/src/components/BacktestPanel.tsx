/**
 * BacktestPanel.tsx — Displays historical backtest results.
 *
 * Layout:
 *   Run selector  — dropdown of past backtest runs (date range + total P&L)
 *   Summary row   — key stats: win rate, total P&L, max drawdown, avg win/loss
 *   Strategy row  — Strategy A vs Strategy B side-by-side P&L
 *   Equity curve  — simple SVG line chart of cumulative P&L over time
 *   Trade table   — all simulated trades for the selected run
 */

import { useState } from 'react'
import {
  useBacktestRuns,
  useBacktestTrades,
  useBacktestEquity,
  BacktestEquityPoint,
} from '../hooks/useBacktest'

// ─── Helpers ──────────────────────────────────────────────────────────────────

function fmt$(n: number | null | undefined): string {
  if (n == null) return '—'
  const abs = Math.abs(n)
  const sign = n < 0 ? '-' : n > 0 ? '+' : ''
  return `${sign}$${abs.toFixed(2)}`
}

function fmtPct(n: number | null | undefined): string {
  if (n == null) return '—'
  return `${(n * 100).toFixed(1)}%`
}

function pnlClass(n: number | null | undefined): string {
  if (n == null) return 'text-gray-500'
  return n > 0 ? 'text-green-600 font-semibold' : n < 0 ? 'text-red-500 font-semibold' : 'text-gray-500'
}

// ─── Equity curve (SVG) ───────────────────────────────────────────────────────

function EquityCurve({ points }: { points: BacktestEquityPoint[] }) {
  if (points.length < 2) return <p className="text-sm text-gray-400">Not enough data to draw curve.</p>

  const W = 600, H = 160, PAD = 8
  const values = points.map(p => p.cumulative_pnl)
  const minV = Math.min(...values)
  const maxV = Math.max(...values)
  const range = maxV - minV || 1

  const x = (i: number) => PAD + (i / (points.length - 1)) * (W - PAD * 2)
  const y = (v: number) => H - PAD - ((v - minV) / range) * (H - PAD * 2)

  const pathD = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(p.cumulative_pnl).toFixed(1)}`).join(' ')
  const zeroY = y(0).toFixed(1)
  const lineColor = values[values.length - 1] >= 0 ? '#16a34a' : '#dc2626'

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-40 rounded-lg bg-gray-50 border border-gray-100">
      {/* Zero baseline */}
      <line x1={PAD} y1={zeroY} x2={W - PAD} y2={zeroY} stroke="#e5e7eb" strokeWidth="1" strokeDasharray="4 2" />
      {/* Equity curve */}
      <path d={pathD} fill="none" stroke={lineColor} strokeWidth="2" strokeLinejoin="round" />
      {/* Start / end labels */}
      <text x={PAD} y={H - 1} fontSize="9" fill="#9ca3af">{points[0].date}</text>
      <text x={W - PAD} y={H - 1} fontSize="9" fill="#9ca3af" textAnchor="end">{points[points.length - 1].date}</text>
    </svg>
  )
}

// ─── Main component ───────────────────────────────────────────────────────────

export function BacktestPanel() {
  const { data: runs, isLoading: runsLoading, error: runsError } = useBacktestRuns()
  const [selectedId, setSelectedId] = useState<string | null>(null)

  // Auto-select the most recent run once data loads
  const activeId = selectedId ?? (runs?.[0]?.id ?? null)
  const activeRun = runs?.find(r => r.id === activeId) ?? null

  const { data: trades, isLoading: tradesLoading } = useBacktestTrades(activeId)
  const { data: equity } = useBacktestEquity(activeId)

  if (runsLoading) return <p className="text-sm text-gray-400 py-4">Loading backtest runs…</p>
  if (runsError)   return <p className="text-sm text-red-500 py-4">Error loading backtests.</p>
  if (!runs || runs.length === 0) {
    return (
      <div className="bg-white border border-gray-200 rounded-xl p-6 text-center">
        <p className="text-gray-500 font-medium">No backtest runs yet.</p>
        <p className="text-sm text-gray-400 mt-1">
          Run <code className="bg-gray-100 px-1 rounded text-xs">python backtest.py --months 3</code> from the <code className="bg-gray-100 px-1 rounded text-xs">bot/</code> directory.
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* ── Run selector ── */}
      <div className="flex items-center gap-3">
        <label className="text-sm font-medium text-gray-700">Backtest run</label>
        <select
          className="text-sm border border-gray-200 rounded-lg px-3 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
          value={activeId ?? ''}
          onChange={e => setSelectedId(e.target.value)}
        >
          {runs.map(r => (
            <option key={r.id} value={r.id}>
              {r.start_date} → {r.end_date} &nbsp;·&nbsp; {fmt$(r.total_pnl)} &nbsp;·&nbsp; {r.total_trades} trades
            </option>
          ))}
        </select>
      </div>

      {activeRun && (
        <>
          {/* ── Summary stats ── */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {[
              { label: 'Total P&L',    value: fmt$(activeRun.total_pnl),         cls: pnlClass(activeRun.total_pnl) },
              { label: 'Win rate',     value: fmtPct(activeRun.win_rate),         cls: 'text-gray-900 font-semibold' },
              { label: 'Max drawdown', value: fmt$(activeRun.max_drawdown),       cls: 'text-red-500 font-semibold' },
              { label: 'Avg win',      value: fmt$(activeRun.avg_win),            cls: 'text-green-600 font-semibold' },
              { label: 'Avg loss',     value: fmt$(activeRun.avg_loss),           cls: 'text-red-500 font-semibold' },
              { label: 'Total trades', value: String(activeRun.total_trades),     cls: 'text-gray-900 font-semibold' },
              { label: 'Wins',         value: String(activeRun.winning_trades),   cls: 'text-green-600 font-semibold' },
              { label: 'Losses',       value: String(activeRun.losing_trades),    cls: 'text-red-500 font-semibold' },
            ].map(s => (
              <div key={s.label} className="bg-white border border-gray-200 rounded-xl px-4 py-3">
                <p className="text-xs text-gray-400 mb-0.5">{s.label}</p>
                <p className={`text-lg ${s.cls}`}>{s.value}</p>
              </div>
            ))}
          </div>

          {/* ── Strategy breakdown ── */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {[
              { label: 'Strategy A — aggressive_3x', pnl: activeRun.strategy_a_pnl, trades: activeRun.strategy_a_trades, color: 'blue' },
              { label: 'Strategy B — conservative_multi', pnl: activeRun.strategy_b_pnl, trades: activeRun.strategy_b_trades, color: 'purple' },
            ].map(s => (
              <div key={s.label} className={`bg-white border border-${s.color}-100 rounded-xl px-4 py-3`}>
                <p className={`text-xs font-medium text-${s.color}-500 mb-1`}>{s.label}</p>
                <p className={`text-2xl ${pnlClass(s.pnl)}`}>{fmt$(s.pnl)}</p>
                <p className="text-xs text-gray-400 mt-0.5">{s.trades} trades</p>
              </div>
            ))}
          </div>

          {/* ── Equity curve ── */}
          <div className="bg-white border border-gray-200 rounded-xl p-4">
            <p className="text-sm font-medium text-gray-700 mb-3">Equity Curve (cumulative P&L)</p>
            {equity && equity.length > 0
              ? <EquityCurve points={equity} />
              : <p className="text-sm text-gray-400">No equity data yet.</p>
            }
          </div>

          {/* ── Trade table ── */}
          <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
            <div className="px-4 py-3 border-b border-gray-100">
              <p className="text-sm font-medium text-gray-700">
                Simulated Trades ({tradesLoading ? '…' : (trades?.length ?? 0)})
              </p>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-gray-50 text-xs text-gray-500 uppercase tracking-wide">
                    <th className="px-4 py-2 text-left">Date</th>
                    <th className="px-4 py-2 text-left">Strategy</th>
                    <th className="px-4 py-2 text-left">Ticker</th>
                    <th className="px-4 py-2 text-right">Entry</th>
                    <th className="px-4 py-2 text-right">Exit</th>
                    <th className="px-4 py-2 text-right">Shares</th>
                    <th className="px-4 py-2 text-right">P&L</th>
                    <th className="px-4 py-2 text-left">Exit reason</th>
                    <th className="px-4 py-2 text-right">Score</th>
                    <th className="px-4 py-2 text-left">Regime</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50">
                  {tradesLoading ? (
                    <tr><td colSpan={10} className="px-4 py-6 text-center text-gray-400">Loading…</td></tr>
                  ) : trades && trades.length > 0 ? trades.map(t => (
                    <tr key={t.id} className="hover:bg-gray-50 transition-colors">
                      <td className="px-4 py-2 text-gray-500 whitespace-nowrap">{t.entry_date}</td>
                      <td className="px-4 py-2">
                        <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                          t.strategy === 'aggressive_3x' ? 'bg-blue-50 text-blue-600' : 'bg-purple-50 text-purple-600'
                        }`}>
                          {t.strategy === 'aggressive_3x' ? 'A' : 'B'}
                        </span>
                      </td>
                      <td className="px-4 py-2 font-medium text-gray-900">{t.ticker}</td>
                      <td className="px-4 py-2 text-right text-gray-600">${t.entry_price.toFixed(2)}</td>
                      <td className="px-4 py-2 text-right text-gray-600">${t.exit_price.toFixed(2)}</td>
                      <td className="px-4 py-2 text-right text-gray-600">{t.shares}</td>
                      <td className={`px-4 py-2 text-right ${pnlClass(t.pnl)}`}>{fmt$(t.pnl)}</td>
                      <td className="px-4 py-2 text-xs text-gray-500 whitespace-nowrap">{t.exit_reason}</td>
                      <td className="px-4 py-2 text-right text-gray-600">{t.conviction_score}/8</td>
                      <td className="px-4 py-2">
                        <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                          t.regime === 'BULL' ? 'bg-green-50 text-green-600' : 'bg-red-50 text-red-600'
                        }`}>
                          {t.regime}
                        </span>
                      </td>
                    </tr>
                  )) : (
                    <tr><td colSpan={10} className="px-4 py-6 text-center text-gray-400">No trades for this run.</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
