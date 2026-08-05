import { useSnooze } from '../hooks/useSnooze'

export function SnoozeControls() {
  const {
    mutate,
    retryRefresh,
    clearRefreshError,
    isPending,
    isError,
    refreshError,
    isRefreshing,
    refreshRetryCount,
  } = useSnooze()

  const hasRefreshError = refreshError !== null
  const shouldDisableSnooze = isPending || isRefreshing

  return (
    <div className="flex flex-col gap-2">
      {hasRefreshError && (
        <div className="flex flex-col gap-2 p-3 bg-red-50 dark:bg-red-950/30 rounded-lg border border-red-200 dark:border-red-800">
          <div className="flex items-center gap-2">
            <span className="text-red-700 dark:text-red-300 font-medium">
              Snooze saved, but Roll state failed to refresh
            </span>
            <button
              type="button"
              onClick={clearRefreshError}
              aria-label="Clear refresh error"
              className="text-red-600 dark:text-red-400 hover:text-red-800 dark:hover:text-red-200 text-xl font-bold leading-none"
            >
              ×
            </button>
          </div>
          <p className="text-sm text-red-600 dark:text-red-400">
            The Roll view may be stale. You can retry refreshing the state.
          </p>
          {refreshRetryCount > 0 && (
            <p className="text-xs text-red-500 dark:text-red-500">
              Retry {refreshRetryCount}/3
            </p>
          )}
          <button
            type="button"
            onClick={retryRefresh}
            disabled={isRefreshing}
            className="w-fit px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-xs font-black uppercase tracking-widest text-stone-300 hover:bg-white/10 disabled:opacity-50 flex items-center gap-2"
          >
            <span className="text-lg">🔄</span>
            {isRefreshing ? 'Refreshing...' : 'Retry Refresh'}
          </button>
        </div>
      )}

      <button
        type="button"
        onClick={() => mutate()}
        disabled={shouldDisableSnooze}
        className="px-4 py-3 glass-button text-xs font-black uppercase tracking-widest disabled:opacity-60"
      >
        {isPending ? 'Saving...' : 'Snooze'}
      </button>

      {isError && (
        <p className="text-sm text-red-600 dark:text-red-400">
          Failed to save snooze
        </p>
      )}
    </div>
  )
}