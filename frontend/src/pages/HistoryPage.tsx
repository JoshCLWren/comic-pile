import { Link } from 'react-router-dom'
import { useMemo } from 'react'
import { useActivity } from '../hooks/useActivity'
import { useIssueCards, indexIssueCards } from '../hooks/useIssueCards'
import CompactIssueCardTrigger from '../components/CompactIssueCardTrigger'
import type { ActivityItem } from '../services/api-activity'
import { formatDate, formatTime } from '../utils/dateFormat'

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

/** Reader-facing name for a logical action the activity resource emits. */
function activityLabel(type: string): string {
  switch (type) {
    case 'roll':
      return 'Rolled'
    case 'snooze':
      return 'Snoozed'
    case 'unsnooze':
      return 'Unsnoozed'
    case 'rate':
      return 'Rated'
    case 'manual_die':
      return 'Set die'
    case 'reset_dice':
      return 'Reset die'
    case 'dismiss':
      return 'Dismissed the roll'
    case 'undo':
      return 'Restored'
    case 'rolled_but_skipped':
      return 'Skipped'
    default:
      return type.replaceAll('_', ' ').replace(/^./, (letter) => letter.toUpperCase())
  }
}

function formatDie(value: number | null | undefined): string | null {
  return value == null ? null : `d${value}`
}

/**
 * Die progression for one logical action.
 *
 * A snooze or rating that stepped the ladder renders its full transition
 * (`d6 → d8`), so the reader can see the die change even though the resulting
 * roll is a separate item. A roll renders the die it was rolled on.
 */
function dieProgression(item: ActivityItem): string | null {
  const before = formatDie(item.die_before)
  const after = formatDie(item.die_after)
  if (before && after && before !== after) return `Die ${before} → ${after}`
  if (after) return `Die ${after}`
  if (before) return `Die ${before}`
  return null
}

function activityHeadline(item: ActivityItem): string {
  const rating = item.rating == null ? null : item.rating.toFixed(1)
  if (item.type === 'rate' && rating) return `Rated ${rating}`
  if (item.type === 'manual_die' && item.die_after != null) return `Set die to d${item.die_after}`
  if (item.type === 'reset_dice' && item.die_after != null) return `Reset die to d${item.die_after}`
  return activityLabel(item.type)
}

/** Subject line for one activity item: an owned series, with its issue. */
function ActivitySubject({ item }: { item: ActivityItem }) {
  if (item.thread_id == null) return null
  const title = item.thread_title ?? 'Deleted series'
  return (
    <span className="text-stone-400">
      {' · '}
      {item.thread_title ? (
        <Link
          to={`/thread/${item.thread_id}`}
          className="underline decoration-dotted underline-offset-2 hover:text-stone-300"
        >
          {title}
        </Link>
      ) : (
        title
      )}
      {item.issue_number ? ` #${item.issue_number}` : null}
    </span>
  )
}

export default function HistoryPage() {
  const {
    data: activity,
    isPending,
    isLoadingMore,
    hasMore,
    loadMore,
    error,
    isRetrying,
    refetch,
  } = useActivity()
  // One bounded batch projection for the visible page of exact owned issues;
  // never one request per rendered row.
  const visibleIssueIds = useMemo(
    () => (activity ?? []).map((item) => item.issue_id).filter((id): id is number => id != null),
    [activity],
  )
  const cardsQuery = useIssueCards(visibleIssueIds)
  const cardsByIssue = useMemo(() => indexIssueCards(cardsQuery.data), [cardsQuery.data])

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

  if (error && !isLoadingMore && (!activity || activity.length === 0)) {
    return (
      <div className="flex flex-col items-center justify-center h-screen gap-4">
        <p role="alert" className="error-message">
          Failed to load activity
        </p>
        <RetryHistoryButton onRetry={() => void refetch()} />
      </div>
    )
  }

  if (!activity || activity.length === 0) {
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
      </header>

      <div
        id="activity-list"
        className="border-y border-[var(--theme-border)] divide-y divide-[var(--theme-border)]"
        role="list"
        aria-label="Activity history"
      >
        {activity.map((item) => {
          const progression = dieProgression(item)
          return (
            <div key={item.event_id} role="listitem" className="flex gap-3 md:gap-4 py-4 px-2 md:px-3">
              <div className="w-16 md:w-20 shrink-0">
                <div className="text-xs font-bold leading-none text-stone-200">
                  {formatDate(item.timestamp)}
                </div>
                <div className="mt-1 text-[10px] font-bold uppercase tracking-widest leading-none text-stone-500">
                  {formatTime(item.timestamp)}
                </div>
              </div>

              <div className="min-w-0 flex-1 space-y-1.5">
                <p className="font-bold text-sm leading-tight text-stone-200 truncate">
                  {activityHeadline(item)}
                  <ActivitySubject item={item} />
                </p>

                {progression && (
                  <p className="text-[10px] font-bold uppercase tracking-widest text-[var(--theme-text-dim)]">
                    {progression}
                  </p>
                )}

                {item.issue_id != null && (
                  <div className="pt-1">
                    <CompactIssueCardTrigger
                      issueId={item.issue_id}
                      threadTitle={item.thread_title ?? 'Deleted series'}
                      issueNumber={item.issue_number ?? cardsByIssue.get(item.issue_id)?.issue_number ?? '?'}
                      status={cardsByIssue.get(item.issue_id)?.status === 'read' ? 'read' : 'unread'}
                      card={cardsByIssue.get(item.issue_id) ?? null}
                      hideTitle
                    />
                  </div>
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

      {error && !isLoadingMore && (
        <div className="text-center py-4">
          <p className="text-sm font-bold text-red-400 mb-3">
            Failed to load more activity
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
            Load more activity
          </button>
        </div>
      )}
    </div>
  )
}
