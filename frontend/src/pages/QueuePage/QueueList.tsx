import type { ReactNode } from 'react'
import type { Thread } from '../../types'
import VirtualizedThreadList, {
  VIRTUALIZATION_THRESHOLD,
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
  scrollRootRef: React.RefObject<HTMLDivElement | null>
  hasNextPage: boolean
  /**
   * Injectable window-virtualizer hook forwarded to VirtualizedThreadList.
   * Production leaves this unset; tests substitute a deterministic virtualizer.
   */
  useVirtualizer?: (options: UseWindowVirtualizerOptions) => QueueVirtualizer
}

/**
 * Renders the active queue presentation, picking between the virtualized
 * window-scrolled list and the plain list based on the bounded page count.
 * The window owns scrolling before and after the virtualization threshold so
 * the queue never introduces a nested scroll container. The empty,
 * search-empty, and reorder-error states are owned here so the page only sees
 * a single composed list region.
 */
export function QueueList({
  activeThreads,
  filteredThreads,
  reorderError,
  renderItem,
  isSearching,
  sentinelRef,
  scrollRootRef,
  hasNextPage,
  useVirtualizer,
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
      <div className="text-center text-stone-500" data-testid="queue-empty">
        No active series in queue
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
      {filteredThreads.length > VIRTUALIZATION_THRESHOLD ? (
        <VirtualizedThreadList 
          threads={filteredThreads} 
          renderItem={renderItem} 
          sentinelRef={sentinelRef}
          scrollRootRef={scrollRootRef}
          hasNextPage={hasNextPage}
          useVirtualizer={useVirtualizer}
        />
      ) : (
        <div
          data-testid="queue-thread-list"
          id="queue-container"
          role="list"
          aria-label="Series queue"
          className="@container overflow-hidden rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] divide-y divide-[var(--theme-border)]"
        >
          {filteredThreads.map((thread, index) => renderItem(thread, index))}
          {hasNextPage && (
            <div ref={sentinelRef} className="h-4" data-testid="queue-infinite-scroll-sentinel" aria-hidden="true" />
          )}
        </div>
      )}
    </>
  )
}
