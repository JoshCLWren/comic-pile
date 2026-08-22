import { useMemo } from 'react'
import type { Thread } from '../../types'

export type QueueSortBy = 'position' | 'alphabetical' | 'created'

/**
 * Derive the active and completed thread partitions plus the sorted
 * presentation list used by QueuePage and its child modules.
 *
 * The hook owns zero cache and zero query state — it only memoizes
 * derived slices so callers can compose them into presentation modules.
 *
 * @param threads - All threads returned by the current page query, in any order.
 * @param sortBy - Sort selector; defaults to queue position.
 */
export function useQueueFilters(
  threads: Thread[] | null | undefined,
  sortBy: QueueSortBy,
) {
const activeThreads = useMemo(
  () => {
    const filtered = threads?.filter((thread) => thread.status === 'active') ?? [];
    return filtered.sort((a, b) => a.queue_position - b.queue_position);
  },
  [threads],
)

  const completedThreads = useMemo(
    () => threads?.filter((thread) => thread.status === 'completed') ?? [],
    [threads],
  )

  const sortedThreads = useMemo(() => {
    if (sortBy === 'alphabetical') {
      return [...activeThreads].sort((a, b) => a.title.localeCompare(b.title))
    }
    if (sortBy === 'created') {
      return [...activeThreads].sort(
        (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
      )
    }
    // position: feasible-only ordering — unblocked threads first, then by user-controlled position
    return [...activeThreads].sort((a, b) => {
      if (a.is_blocked !== b.is_blocked) {
        return a.is_blocked ? 1 : -1
      }
      return a.queue_position - b.queue_position
    })
  }, [activeThreads, sortBy])

  // When search is applied on the backend, the threads array is already filtered.
  // We only need to sort the active threads for presentation.
  const filteredThreads = sortedThreads

  return {
    activeThreads,
    completedThreads,
    sortedThreads,
    filteredThreads,
  }
}
