import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BotStatus } from './components/BotStatus'
import { DailySummary } from './components/DailySummary'
import { TradeLog } from './components/TradeLog'
import { ScanLog } from './components/ScanLog'

const queryClient = new QueryClient()

function Dashboard() {
  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white border-b border-gray-200 px-6 py-4">
        <div className="max-w-7xl mx-auto flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <div>
            <h1 className="text-xl font-bold text-gray-900">Momentum Scanner</h1>
            <p className="text-xs text-gray-400 mt-0.5">Semi-automated · Human-approved trades</p>
          </div>
          <BotStatus />
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-6 py-8 space-y-6">
        <DailySummary />
        <TradeLog />
        <ScanLog />
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
