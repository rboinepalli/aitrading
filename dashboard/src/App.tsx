/**
 * App.tsx — Root component.
 *
 * Layout: header → live position card → trade log table
 *
 * QueryClientProvider wraps the whole app so all hooks (useTrades, usePosition)
 * share one cache. This is the standard TanStack Query setup — same pattern as
 * wrapping with a Redux Provider or Zustand context.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { LivePosition } from './components/LivePosition'
import { TradeLog } from './components/TradeLog'

// One QueryClient for the whole app — manages caching, background refetching, etc.
const queryClient = new QueryClient()

function Dashboard() {
  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white border-b border-gray-200 px-6 py-4">
        <div className="max-w-5xl mx-auto flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold text-gray-900">AI Trading Bot</h1>
            <p className="text-xs text-gray-400 mt-0.5">TQQQ / SQQQ • Paper Trading</p>
          </div>
          <span className="text-xs text-gray-400">v1 · Alpaca Paper</span>
        </div>
      </header>

      {/* Main content */}
      <main className="max-w-5xl mx-auto px-6 py-8 space-y-6">
        {/* Live open position — the most important thing to see at a glance */}
        <LivePosition />

        {/* Full trade history */}
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
