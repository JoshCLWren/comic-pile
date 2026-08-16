import type { ReactNode } from 'react'
import type { Thread } from '../../types'
import VirtualizedThreadList, { VIRTUALIZATION_THRESHOLD } from './VirtualizedThreadList'

interface QueueListProps {
  activeThreads: Thread[]
  filteredThreads: Thread[]
  reorderError: string | null
  renderItem: (thread: Thread, index: number) => ReactNode
  isSearching: boolean
}

/**
 * Renders the active queue presentation, picking between the virtualized
 * multi-column list and the plain grid based on the bounded page count. The
 * empty, search-empty, and reorder-error states are owned here so the page
 * only sees a single composed list region.
 */
export function QueueList({
  activeThreads,
  filteredThreads,
  reorderError,
  renderItem,
  isSearching,
}: QueueListProps) {
  if (isSearching && filteredThreads.length === 0) {
    return (
      <div className="text-center text-stone-500" data-testid="queue-search-empty">
        No active threads match your search
      </div>
    )
  }

  if (activeThreads.length === 0) {
    return (
      <div className="text-center text-stone-500" data-testid="queue-empty">
        No active threads in queue
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
        <VirtualizedThreadList threads={filteredThreads} renderItem={renderItem} />
      ) : (
        <div
          data-testid="queue-thread-list"
          id="queue-container"
          role="list"
          aria-label="Thread queue"
          className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-2 xl:grid-cols-3 gap-4"
        >
          {filteredThreads.map((thread, index) => renderItem(thread, index))}
        </div>
      )}
    </>
  )
}
