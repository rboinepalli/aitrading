/**
 * App.tsx — Root component (v2).
 *
 * Layout:
 *   Header: logo + bot status + regime badge
 *   Row 1:  Strategy A card | Strategy B card
 *   Row 2:  Trade log (both strategies, filterable)
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BotStatus } from './components/BotStatus'
import { StrategyCard } from './components/StrategyCard'
import { TradeLog } from './components/TradeLog'

const queryClient = new QueryClient()

function Dashboard() {
  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white border-b border-gray-200 px-6 py-4">
        <div className="max-w-6xl mx-auto flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <div>
            <h1 className="text-xl font-bold text-gray-900">AI Trading Bot</h1>
            <p className="text-xs text-gray-400 mt-0.5">Paper Trading · Two Strategies</p>
          </div>
          <BotStatus />
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-6 py-8 space-y-6">
        {/* Strategy cards — side by side on desktop, stacked on mobile */}
        <div className="flex flex-col sm:flex-row gap-4">
          <StrategyCard
            strategyName="aggressive_3x"
            displayName="Strategy A"
            description="TQQQ / SQQQ · 3x Leveraged"
            accentColor="blue"
          />
          <StrategyCard
            strategyName="conservative_multi"
            displayName="Strategy B"
            description="QQQ / NVDA / AAPL / MSFT / AMD / SPY"
            accentColor="purple"
          />
        </div>

        {/* Trade log — all strategies */}
        <TradeLog />
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
