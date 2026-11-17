import { Link } from 'react-router-dom'
import { useActivity } from '../hooks/useActivity'
import type { ActivityEvent } from '../types'

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

/**
 * Format the dice progression from die values
 */
function formatDiceProgression(dieBefore: number | null, dieAfter: number | null): string {
  // This is a simplified version - the actual ladder path is preserved in the events
  // For activity events, we show die changes as "d{X} → d{Y}"
  if (dieBefore === null && dieAfter === null) return ''
  if (dieBefore === null) return `d${dieAfter}`
  if (dieAfter === null) return `d${dieBefore}`
  return `d${dieBefore} → d${dieAfter}`
}

/**
 * Get the display value for an event
 */
function getDisplayValue(event: ActivityEvent): string | null {
  switch (event.type) {
    case 'roll':
      // Roll events show dice progression, not a specific result
      // The roll result is not included in the activity API projection
      return null
    case 'rate':
      if (event.rating != null) {
        return `Rated ${event.rating.toFixed(1)}`
      }
      return null
    case 'snooze':
      return `Snoozed to d${event.die_after ?? event.die_before}`
    case 'unsnooze':
      return 'Unsnoozed'
    case 'dismiss':
      return 'Dismissed'
    case 'session_mode':
      return 'Session mode changed'
    default:
      return null
  }
}

/**
 * Get the description for an event (for event cards)
 */
function getEventDescription(event: ActivityEvent): string | null {
  // For roll events, show the die progression
  const diceProgression = formatDiceProgression(event.die_before, event.die_after)
  const parts: string[] = []

  if (diceProgression) {
    parts.push(diceProgression)
  }

  const displayValue = getDisplayValue(event)
  if (displayValue) {
    parts.push(displayValue)
  }

  return parts.join(' · ')
}

export default function HistoryPage() {
  const {
    events,
    isPending,
    isError,
    isLoadingMore,
    hasMore,
    loadMore,
    refetch,
    isRetrying,
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

  if (isError && (!events || events.length === 0)) {
    return (
      <div className="flex flex-col items-center justify-center h-screen gap-4">
        <p role="alert" className="error-message">
          Failed to load activity history
        </p>
        <RetryHistoryButton onRetry={() => void refetch()} />
      </div>
    )
  }

  if (!events || events.length === 0) {
    return (
      <div className="space-y-6 md:space-y-8 pb-20">
        <header className="flex flex-wrap items-end justify-between gap-3 px-2">
          <div>
            <h1 className="text-2xl md:text-4xl font-black tracking-tighter text-glow uppercase leading-none">History</h1>
            <p className="mt-2 text-base font-semibold text-stone-500">Your reading activity history</p>
          </div>
        </header>
        <div className="text-center text-stone-500">No activity yet</div>
      </div>
    )
  }

  const formatDate = (dateStr: string | null | undefined) => {
    if (!dateStr) return ''
    const date = new Date(dateStr)
    if (Number.isNaN(date.getTime())) return ''
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
  }

  const formatTime = (dateStr: string | null | undefined) => {
    if (!dateStr) return ''
    const date = new Date(dateStr)
    if (Number.isNaN(date.getTime())) return ''
    return date.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })
  }

  /**
   * Get issue number display for event
   */
  function getIssueNumberDisplay(event: ActivityEvent): string | null {
    if (!event.issue_number) return null
    return `#${event.issue_number}`
  }

  /**
   * Check if this is a rate event that should show rating separately
   */
  function isRatingEvent(event: ActivityEvent): boolean {
    return event.type === 'rate' && event.rating != null
  }

  return (
    <div className="space-y-6 md:space-y-8 pb-20">
      <header className="flex flex-wrap items-end justify-between gap-3 px-2">
        <div>
          <h1 className="text-2xl md:text-4xl font-black tracking-tighter text-glow uppercase leading-none">History</h1>
          <p className="mt-2 text-base font-semibold text-stone-500">Your reading activity history</p>
        </div>
      </header>

      <div id="events-list" className="border-y border-[var(--theme-border)] divide-y divide-[var(--theme-border)]" role="list" aria-label="Activity history">
        {events.map((event) => {
          const description = getEventDescription(event)
          const isRating = isRatingEvent(event)

          return (
            <div key={event.event_id} role="listitem" className="flex gap-3 md:gap-4 py-4 px-2 md:px-3">
              <div className="w-16 md:w-20 shrink-0">
                <div className="text-xs font-bold leading-none text-stone-200">
                  {formatDate(event.timestamp)}
                </div>
                <div className="mt-1 text-[10px] font-bold uppercase tracking-widest leading-none text-stone-500">
                  {formatTime(event.timestamp)}
                </div>
              </div>

              <div className="min-w-0 flex-1 space-y-1.5">
                <p className="font-bold text-sm leading-tight text-stone-200 truncate">
                  {event.thread_title ? (
                    <>
                      {event.thread_title}
                      {event.issue_number ? (
                        <span className="text-stone-400"> · {getIssueNumberDisplay(event)}</span>
                      ) : null}
                    </>
                  ) : isRating ? (
                    'Rating recorded'
                  ) : event.type === 'session_mode' ? (
                    'Session mode changed'
                  ) : (
                    'Thread unavailable'
                  )}
                </p>
                {description && (
                  <p className="text-xs text-stone-400">
                    {description}
                  </p>
                )}
              </div>
            </div>
          )
        })}
      </div>

      {isLoadingMore && (
        <div className="flex items-center justify-center py-8">
          <div className="text-sm font-bold text-stone-400 animate-pulse">
            Loading more...
          </div>
        </div>
      )}

      {isError && !isLoadingMore && (
        <div className="text-center py-4">
          <p className="text-sm font-bold text-red-400 mb-3">
            Failed to load more events
          </p>
          <button
            onClick={loadMore}
            className="h-9 px-4 rounded-lg border border-[var(--theme-border)] text-xs font-bold text-[var(--theme-text-muted)] hover:text-[var(--theme-text-primary)] transition-colors"
          >
            Retry
          </button>
        </div>
      )}

      {hasMore && !isLoadingMore && (
        <div className="flex justify-center pt-4 pb-8">
          <button
            onClick={loadMore}
            className="h-10 md:h-12 px-6 md:px-8 rounded-lg border border-[var(--theme-border)] text-xs font-bold text-[var(--theme-text-muted)] hover:text-[var(--theme-text-primary)] transition-colors"
          >
            Load More Events
          </button>
        </div>
      )}
    </div>
  )
}