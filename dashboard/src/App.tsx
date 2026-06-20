/**
 * App.tsx — Root component (v3).
 *
 * Layout:
 *   Header: logo + bot status + regime badge
 *   Row 1:  Strategy A | Strategy B | Strategy C (3-column grid)
 *   Row 2:  Trade log (all three strategies)
 *   Row 3:  Backtest results
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BotStatus } from './components/BotStatus'
import { StrategyCard } from './components/StrategyCard'
import { TradeLog } from './components/TradeLog'
import { BacktestPanel } from './components/BacktestPanel'

const queryClient = new QueryClient()

function Dashboard() {
  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white border-b border-gray-200 px-6 py-4">
        <div className="max-w-7xl mx-auto flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <div>
            <h1 className="text-xl font-bold text-gray-900">AI Trading Bot</h1>
            <p className="text-xs text-gray-400 mt-0.5">Paper Trading · Three Strategies</p>
          </div>
          <BotStatus />
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-6 py-8 space-y-6">
        {/* Strategy cards — 3 columns on desktop, stacked on mobile */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <StrategyCard
            strategyName="aggressive_3x"
            displayName="Strategy A"
            description="TQQQ / SQQQ · 3× Nasdaq"
            accentColor="blue"
          />
          <StrategyCard
            strategyName="momentum_stocks"
            displayName="Strategy B"
            description="NVDA · AAPL · MSFT · AMD · TSLA · META · COIN"
            accentColor="purple"
          />
          <StrategyCard
            strategyName="aggressive_semis"
            displayName="Strategy C"
            description="SOXL / SOXS · 3× Semiconductors"
            accentColor="orange"
          />
        </div>

        {/* Trade log — all strategies */}
        <TradeLog />

        {/* Backtest results */}
        <section>
          <h2 className="text-base font-semibold text-gray-700 mb-3">Backtest Results</h2>
          <BacktestPanel />
        </section>
      </main>
    </div>
  )
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <Dashboard />
    </QueryClientProvider>
  )
}
