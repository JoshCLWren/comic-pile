import { Link } from 'react-router-dom'
import { useActivity } from '../hooks/useActivity'
import type { ActivityEvent } from '../services/api-activity'

function eventLabel(event: ActivityEvent): string {
  const title = event.thread_title ?? 'Deleted series'
  return event.issue_number ? `${title} #${event.issue_number}` : title
}

function formatTimestamp(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

export default function HistoryPage() {
  const { events, isPending, isRetrying, isError, isLoadingMore, hasMore, loadMore, refetch } = useActivity()

  return (
    <div className="space-y-6 pb-20">
      <header className="flex flex-wrap items-end justify-between gap-3 px-2">
        <div>
          <h1 className="text-2xl font-black tracking-tighter text-[var(--theme-text-primary)] md:text-4xl">History</h1>
          <p className="mt-2 text-sm text-[var(--theme-text-muted)]">Your reading activity</p>
        </div>
        <button
          type="button"
          onClick={() => void refetch()}
          className="h-9 rounded-lg border border-[var(--theme-border)] px-4 text-sm font-semibold text-[var(--theme-text-primary)] hover:bg-[var(--theme-bg-hover)]"
        >
          Refresh
        </button>
      </header>

      {isPending ? (
        <div className="space-y-2">
          <p role="status">{isRetrying ? 'Still loading your history… your library is safe.' : 'Loading your history…'}</p>
          {isRetrying ? <button type="button" onClick={() => void refetch()} className="underline">Retry</button> : null}
        </div>
      ) : null}
      {isError ? (
        <div role="alert" className="space-y-2 text-[var(--theme-error)]">
          <p>Failed to load your history.</p>
          <button type="button" onClick={() => void refetch()} className="underline">Retry</button>
        </div>
      ) : null}
      {!isPending && !isError && events.length === 0 ? (
        <p className="text-[var(--theme-text-muted)]">No activity yet</p>
      ) : null}

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

      {hasMore ? (
        <button
          type="button"
          disabled={isLoadingMore}
          onClick={() => void loadMore()}
          className="h-10 rounded-lg border border-[var(--theme-border)] px-4 text-sm font-semibold text-[var(--theme-text-primary)] hover:bg-[var(--theme-bg-hover)] disabled:opacity-50"
        >
          {isLoadingMore ? 'Loading…' : 'Load more'}
        </button>
      ) : null}
    </div>
  )
}
