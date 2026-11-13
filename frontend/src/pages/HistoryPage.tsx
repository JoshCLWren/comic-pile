import { Link } from 'react-router-dom'
import { useActivity } from '../hooks/useActivity'
import type { ActivityEvent } from '../services/api-activity'

/**
 * Shared recovery action for the bounded-loading and load-failure states.
 *
 * Both states offer the same recovery, so they share one button treatment per
 * the visual grammar's button-group rule.
 */
function RetryHistoryButton({ onRetry }: { onRetry: () => void }) {
  return (
    <button
      type="button"
      onClick={onRetry}
      className="h-9 px-4 rounded-lg border border-[var(--theme-border)] text-xs font-bold text-[var(--theme-text-muted)] hover:text-[var(--theme-text-primary)] transition-colors"
    >
      Retry
    </button>
  )
}

function eventLabel(event: ActivityEvent): string {
  const title = event.thread_title ?? 'Deleted series'
  return event.issue_number ? `${title} #${event.issue_number}` : title
}

function formatTimestamp(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

export default function HistoryPage() {
  const {
    events,
    isPending,
    isRetrying,
    isError,
    isFetchNextPageError,
    isLoadingMore,
    hasMore,
    loadMore,
    refetch,
  } = useActivity()

  if (isPending) {
    // A timed-out first page stays pending through the shared retry policy
    // (issue #3429). Once an attempt has failed, say so and offer recovery
    // instead of holding a bare spinner until retries exhaust. isRetrying stays
    // true across a user-initiated retry, so pressing Retry never drops the user
    // back onto the bare splash.
    if (isRetrying) {
      return (
        <div className="flex flex-col items-center justify-center h-screen gap-4">
          <p role="status" className="text-sm font-bold text-stone-400">
            Still loading your history… your library is safe.
          </p>
          <RetryHistoryButton onRetry={() => void refetch()} />
        </div>
      )
    }
    return <div className="flex items-center justify-center h-screen">Loading...</div>
  }

  if (isError && !isLoadingMore && events.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-screen gap-4">
        <p role="alert" className="error-message">
          Failed to load history
        </p>
        <RetryHistoryButton onRetry={() => void refetch()} />
      </div>
    )
  }

  if (!isPending && !isError && events.length === 0) {
    return (
      <div className="space-y-6 md:space-y-8 pb-20">
        <header className="flex flex-wrap items-end justify-between gap-3 px-2">
          <div>
            <h1 className="text-2xl md:text-4xl font-black tracking-tighter text-glow uppercase leading-none">History</h1>
            <p className="mt-2 text-base font-semibold text-stone-500">Your reading activity</p>
          </div>
        </header>
        <div className="text-center text-stone-500">No activity yet</div>
      </div>
    )
  }

  return (
    <div className="space-y-6 md:space-y-8 pb-20">
      <header className="flex flex-wrap items-end justify-between gap-3 px-2">
        <div>
          <h1 className="text-2xl md:text-4xl font-black tracking-tighter text-glow uppercase leading-none">History</h1>
          <p className="mt-2 text-base font-semibold text-stone-500">Your reading activity</p>
        </div>
        <button
          type="button"
          onClick={() => void refetch()}
          className="h-9 px-4 rounded-lg border border-[var(--theme-border)] text-xs font-bold text-[var(--theme-text-muted)] hover:text-[var(--theme-text-primary)] transition-colors"
        >
          Refresh
        </button>
      </header>

      {events.length > 0 ? (
        <div role="list" aria-label="Reading activity" className="divide-y divide-[var(--theme-border)] border-y border-[var(--theme-border)]">
          {events.map((event) => (
            <div key={event.event_id} role="listitem" className="flex gap-3 px-2 py-4 md:gap-4 md:px-3">
              <time dateTime={event.timestamp} className="w-28 shrink-0 text-xs text-[var(--theme-text-muted)]">
                {formatTimestamp(event.timestamp)}
              </time>
              <div className="min-w-0 space-y-1">
                <p className="text-sm font-semibold text-[var(--theme-text-primary)]">{event.action_display}</p>
                {event.thread_id ? (
                  <Link to={`/thread/${event.thread_id}${event.issue_id ? `?issue=${event.issue_id}` : ''}`} className="text-xs text-[var(--theme-personal-accent)] underline underline-offset-2">
                    {eventLabel(event)}
                  </Link>
                ) : (
                  <p className="text-xs text-[var(--theme-text-dim)]">{eventLabel(event)}</p>
                )}
              </div>
            </div>
          ))}
        </div>
      ) : null}

      {isLoadingMore && (
        <div className="flex items-center justify-center py-8">
          <div className="text-sm font-bold text-stone-400 animate-pulse">
            Loading more...
          </div>
        </div>
      )}

      {isError && !isLoadingMore && events.length > 0 && (
        <div className="text-center py-4">
          <p className="text-sm font-bold text-red-400 mb-3">
            {isFetchNextPageError ? 'Failed to load more history' : 'Failed to refresh history'}
          </p>
          <button
            type="button"
            onClick={() => void (isFetchNextPageError ? loadMore() : refetch())}
            className="h-9 px-4 rounded-lg border border-[var(--theme-border)] text-xs font-bold text-[var(--theme-text-muted)] hover:text-[var(--theme-text-primary)] transition-colors"
          >
            Retry
          </button>
        </div>
      )}

      {hasMore && !isLoadingMore && (
        <div className="flex justify-center pt-4 pb-8">
          <button
            onClick={() => void loadMore()}
            className="h-10 md:h-12 px-6 md:px-8 rounded-lg border border-[var(--theme-border)] text-xs font-bold text-[var(--theme-text-muted)] hover:text-[var(--theme-text-primary)] transition-colors"
          >
            Load More Activity
          </button>
        </div>
      )}
    </div>
  )
}