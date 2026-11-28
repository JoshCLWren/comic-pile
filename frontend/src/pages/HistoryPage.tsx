import { Link } from 'react-router-dom'
import { useMemo, useState, useCallback } from 'react'
import { useActivity } from '../hooks/useActivity'
import { useDebounce } from '../hooks/useDebounce'
import { useIssueCards, indexIssueCards } from '../hooks/useIssueCards'
import CompactIssueCardTrigger from '../components/CompactIssueCardTrigger'
import HistoryFilters from './HistoryFilters'
import type { ActivityItem } from '../services/api-activity'
import {
  EMPTY_ACTIVITY_FILTERS,
  hasActiveActivityFilters,
  normalizeActivityFilters,
  type ActivityFilters,
} from '../utils/activityFilters'
import { activityLabel } from '../utils/activityLabels'
import { formatDate, formatTime } from '../utils/dateFormat'
import { issuesApi } from '../services/api-issues'
import { queryClient } from '../query/queryClient'
import { invalidateAfterIssueEdit, invalidateAfterQueueMutation } from '../query/cacheEffects'
import { useBulkReadOperations } from '../hooks/useBulkReadOperations'
import { collectAllPages, MAX_ISSUE_COLLECTION_PAGES } from '../pagination/collectAllPages'

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
 * Resolve a canonical owned issue id from the owner-scoped activity projection.
 *
 * Sessionless history can contain legacy events that only carry a thread title
 * and issue number. Those hints are never an owned issue identity, so they must
 * not be promoted into a card, cover, or mapping target. A non-positive or
 * non-integer placeholder is rejected for the same reason.
 */
function canonicalActivityIssueId(id: number | null | undefined): number | null {
  return id != null && Number.isInteger(id) && id > 0 ? id : null
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

const FILTER_DEBOUNCE_MS = 400

export default function HistoryPage() {
  // Text inputs are locally owned and debounced so typing does not issue a
  // request per keystroke; select/date changes also settle through the same
  // short quiet period. The applied filters feed both the query key and the
  // server request, so chronology and pagination stay resource-owned.
  const [filterDraft, setFilterDraft] = useState<ActivityFilters>(EMPTY_ACTIVITY_FILTERS)
  const debouncedQuery = useDebounce(filterDraft.q, FILTER_DEBOUNCE_MS)
  const debouncedSeries = useDebounce(filterDraft.series, FILTER_DEBOUNCE_MS)
  const filters = useMemo(
    () =>
      normalizeActivityFilters({
        ...filterDraft,
        q: debouncedQuery,
        series: debouncedSeries,
      }),
    [filterDraft, debouncedQuery, debouncedSeries],
  )
  const hasFilters = hasActiveActivityFilters(filters)
  const clearFilters = useCallback(() => setFilterDraft(EMPTY_ACTIVITY_FILTERS), [])
  const {
    data: activity,
    isPending,
    isLoadingMore,
    hasMore,
    loadMore,
    error,
    isRetrying,
    refetch,
  } = useActivity(filters)
  const [restoringThreadId, setRestoringThreadId] = useState<number | null>(null)
  const [restoreMessage, setRestoreMessage] = useState<string | null>(null)
  const {
    operations: bulkReadOperations,
    message: bulkUndoMessage,
    undo: undoBulkRead,
  } = useBulkReadOperations(issuesApi)
  // One bounded batch projection for the visible page of exact owned issues;
  // never one request per rendered row.
  const visibleIssueIds = useMemo(
    () => (activity ?? [])
      .map((item) => canonicalActivityIssueId(item.issue_id))
      .filter((id): id is number => id != null),
    [activity],
  )
  const cardsQuery = useIssueCards(visibleIssueIds)
  const cardsByIssue = useMemo(() => indexIssueCards(cardsQuery.data), [cardsQuery.data])

  // Controls stay mounted across loading, failure and empty states so a reader
  // can change or clear a filter without waiting for the current request.
  const pageHeader = (
    <header className="flex flex-wrap items-end justify-between gap-3 px-2">
      <div>
        <h1 className="text-2xl md:text-4xl font-black tracking-tighter text-glow uppercase leading-none">History</h1>
        <p className="mt-2 text-base font-semibold text-stone-500">Your reading activity</p>
        {restoreMessage && <p className="mt-2 text-sm text-stone-400">{restoreMessage}</p>}
        {bulkUndoMessage && (
          <p className="mt-2 text-sm text-stone-400" role="status">{bulkUndoMessage}</p>
        )}
      </div>
    </header>
  )
  const filterPanel = (
    <div className="px-2">
      <HistoryFilters filters={filterDraft} onChange={setFilterDraft} onClear={clearFilters} />
    </div>
  )

  const handleRestoreUnread = useCallback(async (threadId: number) => {
    setRestoringThreadId(threadId)
    setRestoreMessage(null)
    try {
      const collected = await collectAllPages({
        fetchPage: (token) => issuesApi.list(threadId, {
          status: 'read', page_size: 100, page_token: token ?? undefined,
        }),
        selectItems: (page) => page.issues.map((issue) => issue.id),
        selectNextToken: (page) => page.next_page_token || null,
        maxPages: MAX_ISSUE_COLLECTION_PAGES,
      })
      if (collected.stopReason === 'max-pages') {
        throw new Error('Unable to load every read issue for this series.')
      }
      const ids = collected.items
      if (ids.length === 0) {
        setRestoreMessage('No read issues to restore.')
        return
      }
      await issuesApi.bulkMarkUnread(ids)
      await invalidateAfterQueueMutation(queryClient)
      await invalidateAfterIssueEdit(queryClient, threadId)
      setRestoreMessage('Restored read issues to unread.')
    } catch {
      setRestoreMessage('Failed to restore unread issues.')
    } finally {
      setRestoringThreadId(null)
    }
  }, [])

  if (isPending) {
    // A timed-out first page stays pending through the shared retry policy
    // (issue #3429). Once an attempt has failed, say so and offer recovery
    // instead of holding a bare spinner until retries exhaust. isRetrying stays
    // true across a user-initiated retry, so pressing Retry never drops the user
    // back onto the bare splash.
    if (isRetrying) {
      return (
        <div className="space-y-6 md:space-y-8 pb-20">
          {pageHeader}
          {filterPanel}
          <div className="flex flex-col items-center justify-center gap-4 py-20">
            <p role="status" className="text-sm font-bold text-stone-400">
              Still loading your history… your library is safe.
            </p>
            <RetryHistoryButton onRetry={() => void refetch()} />
          </div>
        </div>
      )
    }
    return (
      <div className="space-y-6 md:space-y-8 pb-20">
        {pageHeader}
        {filterPanel}
        <div className="flex items-center justify-center py-20">Loading...</div>
      </div>
    )
  }

  if (error && !isLoadingMore && (!activity || activity.length === 0)) {
    return (
      <div className="space-y-6 md:space-y-8 pb-20">
        {pageHeader}
        {filterPanel}
        <div className="flex flex-col items-center justify-center gap-4 py-20">
          <p role="alert" className="error-message">
            Failed to load activity
          </p>
          <RetryHistoryButton onRetry={() => void refetch()} />
        </div>
      </div>
    )
  }

  if (!activity || activity.length === 0) {
    return (
      <div className="space-y-6 md:space-y-8 pb-20">
        {pageHeader}
        {filterPanel}
        <div className="text-center text-stone-500" role="status">
          {hasFilters ? 'No activity matches these filters' : 'No activity yet'}
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6 md:space-y-8 pb-20">
      {pageHeader}
      {filterPanel}

      {bulkReadOperations.length > 0 && (
        <section
          className="surface-panel rounded-lg border border-[var(--theme-border)] p-3 md:p-4 space-y-2"
          data-testid="bulk-read-operations"
          aria-label="Reviewable bulk reads"
        >
          <h2 className="text-sm font-black uppercase tracking-wider text-[var(--theme-text-primary)]">
            Reviewable bulk reads
          </h2>
          <ul className="divide-y divide-[var(--theme-border)]">
            {bulkReadOperations.map(({ threadId, operation }) => (
              <li key={operation.id} className="flex flex-wrap items-center justify-between gap-3 py-2">
                <span className="text-xs text-[var(--theme-text-muted)]">
                  Operation #{operation.id} · {operation.items.length} issue
                  {operation.items.length === 1 ? '' : 's'} · series {threadId}
                </span>
                <button
                  type="button"
                  className="text-[10px] font-bold uppercase tracking-widest text-[var(--theme-text-primary)] underline disabled:opacity-50"
                  onClick={() => void undoBulkRead(threadId, operation.id)}
                >
                  Undo
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      <div
        id="activity-list"
        className="border-y border-[var(--theme-border)] divide-y divide-[var(--theme-border)]"
        role="list"
        aria-label="Activity history"
      >
        {activity.map((item) => {
          const progression = dieProgression(item)
          const canonicalIssueId = canonicalActivityIssueId(item.issue_id)
          return (
            <div key={item.event_id} role="listitem" className="flex gap-3 md:gap-4 py-4 px-2 md:px-3">
              <div className="w-16 md:w-20 shrink-0">
                <div className="text-xs font-bold leading-none text-stone-200">
                  {formatDate(item.timestamp)}
                </div>
                <div className="mt-1 text-[10px] font-bold uppercase tracking-widest leading-none text-stone-500">
                  {formatTime(item.timestamp)}
                </div>
                {item.session_id != null && (
                  <Link
                    to={`/sessions/${item.session_id}`}
                    className="mt-2 inline-block text-[10px] font-bold uppercase tracking-widest text-[var(--theme-text-muted)] underline decoration-dotted underline-offset-2 hover:text-[var(--theme-text-primary)]"
                  >
                    Session
                  </Link>
                )}
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

                {canonicalIssueId != null && (
                  <div className="pt-1" data-testid="history-issue-actions">
                    <CompactIssueCardTrigger
                      issueId={canonicalIssueId}
                      threadTitle={item.thread_title ?? 'Deleted series'}
                      issueNumber={item.issue_number ?? cardsByIssue.get(canonicalIssueId)?.issue_number ?? '?'}
                      status={cardsByIssue.get(canonicalIssueId)?.status === 'read' ? 'read' : 'unread'}
                      card={cardsByIssue.get(canonicalIssueId) ?? null}
                      hideTitle
                    />
                  </div>
                )}
                {item.thread_id != null && (
                  <div className="flex gap-3 pt-1">
                    <Link
                      to={`/thread/${item.thread_id}`}
                      className="text-[10px] font-bold uppercase tracking-widest text-stone-500 hover:text-stone-300 underline"
                    >
                      Open series
                    </Link>
                    <button
                      type="button"
                      className="text-[10px] font-bold uppercase tracking-widest text-stone-500 hover:text-stone-300 underline disabled:opacity-50"
                      disabled={restoringThreadId === item.thread_id}
                      onClick={() => void handleRestoreUnread(item.thread_id!)}
                    >
                      {restoringThreadId === item.thread_id ? 'Restoring…' : 'Restore unread'}
                    </button>
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
