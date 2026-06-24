import { useBotState } from '../hooks/useBotState'

export function BotStatus() {
  const { data: state, isLoading } = useBotState()

  const halted   = state?.trading_halted ?? false
  const loss     = state?.daily_loss ?? 0
  const openPos  = state?.positions_open ?? 0

  return (
    <div className="flex items-center gap-3 flex-wrap">
      <span className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold ${
        isLoading ? 'bg-gray-100 text-gray-500' :
        halted    ? 'bg-red-100 text-red-700'   : 'bg-emerald-100 text-emerald-700'
      }`}>
        <span className={`w-1.5 h-1.5 rounded-full ${
          isLoading ? 'bg-gray-400' : halted ? 'bg-red-500' : 'bg-emerald-500 animate-pulse'
        }`} />
        {isLoading ? 'Connecting...' : halted ? 'HALTED' : 'ACTIVE'}
      </span>

      {!isLoading && (
        <>
          <span className="text-xs text-gray-500">
            {openPos} open position{openPos !== 1 ? 's' : ''}
          </span>
          <span className={`text-xs font-medium ${loss < 0 ? 'text-red-600' : 'text-gray-400'}`}>
            Daily P&L: {loss >= 0 ? '+' : ''}${loss.toFixed(2)}
          </span>
        </>
      )}

      {halted && state?.halt_reason && (
        <span className="text-xs text-red-500 hidden sm:block truncate max-w-xs">
          {state.halt_reason}
        </span>
      )}
    </div>
  )
}
