import type { ReactNode } from 'react'
import type { ThreadListItem } from '../../types'
import VirtualizedThreadList, {
  type QueueVirtualizer,
  type UseWindowVirtualizerOptions,
} from './VirtualizedThreadList'

interface QueueSearchMatch {
  id: number
  title: string
  status: 'completed' | 'excluded'
}

interface QueueListProps {
  activeThreads: ThreadListItem[]
  filteredThreads: ThreadListItem[]
  /** Whole-queue active total, including rows outside the loaded result pages. */
  activeCount?: number
  reorderError: string | null
  renderItem: (thread: ThreadListItem, index: number) => ReactNode
  isSearching: boolean
  sentinelRef: React.Ref<HTMLDivElement>
  hasNextPage: boolean
  isLoading?: boolean
  /** Completed/removed series that match the current search (#4655). */
  completedMatches?: QueueSearchMatch[]
  excludedMatches?: QueueSearchMatch[]
  onOpenCompletedSeries?: (threadId: number) => void
  onRestoreCompletedSeries?: (threadId: number) => void
  onOpenExcludedSeries?: (threadId: number) => void
  /**
   * Opens the existing series-create flow. The Queue page wires this to the
   * create modal; direct list consumers (tests, regression harnesses) may
   * omit it, in which case the empty state renders copy only.
   */
  onAddSeries?: () => void
  /**
   * Injectable window-virtualizer hook forwarded to VirtualizedThreadList.
   * Production leaves this unset; tests substitute a deterministic virtualizer.
   */
  useVirtualizer?: (options: UseWindowVirtualizerOptions) => QueueVirtualizer
}

/**
 * Renders the active queue presentation using the virtualized window-scrolled
 * list for every page. The window owns scrolling so the queue never introduces
 * a nested scroll container. The empty, search-empty, and reorder-error states
 * are owned here so the page only sees a single composed list region.
 */
export function QueueList({
  activeThreads,
  filteredThreads,
  activeCount = activeThreads.length,
  reorderError,
  renderItem,
  isSearching,
  sentinelRef,
  hasNextPage,
  useVirtualizer,
  onAddSeries,
  isLoading = false,
  completedMatches = [],
  excludedMatches = [],
  onOpenCompletedSeries,
  onRestoreCompletedSeries,
  onOpenExcludedSeries,
}: QueueListProps) {
  // The current filtered page can be empty while its replacement request is
  // still loading. Use the whole-queue total, not the loaded row count, to
  // distinguish that pending state from a settled empty Queue (#3912/#3614).
  if (isSearching && filteredThreads.length === 0 && activeCount > 0 && isLoading) {
    return (
      <div
        role="status"
        className="text-center text-[var(--theme-text-muted)] py-8"
        data-testid="queue-search-loading"
      >
        Loading series...
      </div>
    )
  }

  if (isSearching && filteredThreads.length === 0) {
    const hasOtherMatches = completedMatches.length > 0 || excludedMatches.length > 0
    return (
      <div className="text-center text-[var(--theme-text-dim)] space-y-4" data-testid="queue-search-empty">
        <p>No active series match your search.</p>
        {hasOtherMatches ? (
          <div className="space-y-3 text-left max-w-xl mx-auto">
            <p className="text-sm text-[var(--theme-text-muted)]">
              Found in completed or removed series:
            </p>
            {completedMatches.map((match) => (
              <div key={`completed-${match.id}`} className="flex items-center justify-between gap-3 rounded-lg border border-[var(--theme-border)] px-3 py-2">
                <div>
                  <p className="text-sm font-semibold text-[var(--theme-text-primary)]">{match.title}</p>
                  <p className="text-xs text-[var(--theme-text-dim)]">Completed</p>
                </div>
                <div className="flex gap-2">
                  <button
                    type="button"
                    className="text-xs font-bold text-[var(--theme-text-muted)] hover:text-[var(--theme-text-primary)] underline"
                    onClick={() => onOpenCompletedSeries?.(match.id)}
                  >
                    Open completed
                  </button>
                  <button
                    type="button"
                    className="text-xs font-bold text-[var(--theme-text-muted)] hover:text-[var(--theme-text-primary)] underline"
                    onClick={() => onRestoreCompletedSeries?.(match.id)}
                  >
                    Restore unread
                  </button>
                </div>
              </div>
            ))}
            {excludedMatches.map((match) => (
              <div key={`excluded-${match.id}`} className="flex items-center justify-between gap-3 rounded-lg border border-[var(--theme-border)] px-3 py-2">
                <div>
                  <p className="text-sm font-semibold text-[var(--theme-text-primary)]">{match.title}</p>
                  <p className="text-xs text-[var(--theme-text-dim)]">Removed</p>
                </div>
                <button
                  type="button"
                  className="text-xs font-bold text-[var(--theme-text-muted)] hover:text-[var(--theme-text-primary)] underline"
                  onClick={() => onOpenExcludedSeries?.(match.id)}
                >
                  Open removed
                </button>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-sm text-[var(--theme-text-muted)]">
            No completed or removed series match this search either.
          </p>
        )}
      </div>
    )
  }

  if (activeThreads.length === 0) {
    return (
      <div
        className="flex flex-col items-center px-4 py-6 text-center"
        data-testid="queue-empty"
      >
        <div className="text-4xl" aria-hidden="true">
          🎲
        </div>
        <div className="mt-4 space-y-1">
          <p className="text-base font-bold text-[var(--theme-text-primary)]">
            Nothing to roll yet
          </p>
          <p className="text-xs text-[var(--theme-text-dim)]">
            Your reading queue is empty — add some comic series to get started.
          </p>
        </div>
        {onAddSeries && (
          <button
            type="button"
            onClick={onAddSeries}
            data-testid="queue-empty-add-series"
            className="mt-4 h-11 min-h-[44px] w-full sm:w-auto sm:min-w-52 px-5 rounded-xl bg-[var(--theme-primary-action)] text-sm font-black text-[var(--theme-primary-action-text)] hover:bg-[var(--theme-primary-action-hover)] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--theme-bg-page)]"
          >
            Add Series
          </button>
        )}
      </div>
    )
  }

  return (
    <>
      {reorderError && (
        <div
          className="bg-red-500/10 border border-red-500/30 text-red-400 px-4 py-3 rounded-xl text-sm font-medium"
          data-testid="queue-reorder-error"
        >
          {reorderError}
        </div>
      )}
      <VirtualizedThreadList
        threads={filteredThreads}
        renderItem={renderItem}
        sentinelRef={sentinelRef}
        hasNextPage={hasNextPage}
        useVirtualizer={useVirtualizer}
      />
    </>
  )
}
