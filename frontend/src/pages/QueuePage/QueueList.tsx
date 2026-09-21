import type { ReactNode } from 'react'
import type { Thread } from '../../types'
import VirtualizedThreadList, {
  type QueueVirtualizer,
  type UseWindowVirtualizerOptions,
} from './VirtualizedThreadList'

interface QueueListProps {
  activeThreads: Thread[]
  filteredThreads: Thread[]
  reorderError: string | null
  renderItem: (thread: Thread, index: number) => ReactNode
  isSearching: boolean
  sentinelRef: React.Ref<HTMLDivElement>
  hasNextPage: boolean
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
  reorderError,
  renderItem,
  isSearching,
  sentinelRef,
  hasNextPage,
  useVirtualizer,
  onAddSeries,
}: QueueListProps) {
  if (isSearching && filteredThreads.length === 0) {
    return (
      <div className="text-center text-stone-500" data-testid="queue-search-empty">
        No active series match your search
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
          <p className="text-sm text-stone-300 font-bold uppercase tracking-widest">
            Nothing to roll yet
          </p>
          <p className="text-xs text-stone-500">
            Your reading queue is empty — add some comic series to get started.
          </p>
        </div>
        {onAddSeries && (
          <button
            type="button"
            onClick={onAddSeries}
            data-testid="queue-empty-add-series"
            className="mt-4 h-11 min-h-[44px] w-full sm:w-auto sm:min-w-52 px-5 rounded-xl bg-[var(--theme-primary-action)] text-sm font-black text-stone-950 hover:bg-[var(--theme-primary-action-hover)] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--theme-bg-page)]"
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
