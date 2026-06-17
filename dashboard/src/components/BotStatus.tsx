/**
 * BotStatus.tsx — Header bar showing regime, VIX, and bot activity.
 * Reads from the bot_events table (latest row tells us what the bot last did).
 */

import { useBotStatus } from '../hooks/useBotStatus'
import { formatDistanceToNow } from 'date-fns'

const REGIME_STYLES: Record<string, { bg: string; text: string; label: string }> = {
  BULL:   { bg: 'bg-green-100',  text: 'text-green-800',  label: 'BULL'   },
  BEAR:   { bg: 'bg-red-100',    text: 'text-red-800',    label: 'BEAR'   },
  CHOPPY: { bg: 'bg-yellow-100', text: 'text-yellow-800', label: 'CHOPPY' },
}

function extractRegime(message: string): string | null {
  if (message.includes('BULL'))   return 'BULL'
  if (message.includes('BEAR'))   return 'BEAR'
  if (message.includes('CHOPPY')) return 'CHOPPY'
  return null
}

export function BotStatus() {
  const { data: event, isLoading } = useBotStatus()

  const regime = event ? extractRegime(event.message) : null
  const regimeStyle = regime ? REGIME_STYLES[regime] : null
  const lastSeen = event
    ? formatDistanceToNow(new Date(event.timestamp), { addSuffix: true })
    : null

  const isActive = event?.event_type === 'STARTED' || event?.event_type === 'REGIME_CHANGE'

  return (
    <div className="flex items-center gap-3 flex-wrap">
      {/* Bot status pill */}
      <span className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold ${
        isLoading ? 'bg-gray-100 text-gray-500' :
        isActive  ? 'bg-emerald-100 text-emerald-700' : 'bg-gray-100 text-gray-500'
      }`}>
        <span className={`w-1.5 h-1.5 rounded-full ${isActive ? 'bg-emerald-500 animate-pulse' : 'bg-gray-400'}`} />
        {isLoading ? 'Connecting...' : isActive ? 'ACTIVE' : 'SLEEPING'}
      </span>

      {/* Regime badge */}
      {regimeStyle && (
        <span className={`inline-block px-3 py-1 rounded-full text-xs font-bold ${regimeStyle.bg} ${regimeStyle.text}`}>
          {regimeStyle.label}
        </span>
      )}

      {/* Last seen */}
      {lastSeen && (
        <span className="text-xs text-gray-400">last tick {lastSeen}</span>
      )}

      {/* Latest message */}
      {event?.message && (
        <span className="text-xs text-gray-500 hidden sm:block truncate max-w-xs">
          {event.message}
        </span>
      )}
    </div>
  )
}
