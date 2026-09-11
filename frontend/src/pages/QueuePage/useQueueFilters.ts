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
    const filtered = threads?.filter((thread) => thread.status === 'active') ?? []
    // Position keeps the user-controlled order client-side. Alphabetical and
    // created preserve the server's keyset-cursor order so appended pages
    // never reshuffle already-loaded rows.
    if (sortBy === 'position') {
      return [...filtered].sort((a, b) => a.queue_position - b.queue_position)
    }
    return filtered
  },
  [threads, sortBy],
)

  const completedThreads = useMemo(
    () => threads?.filter((thread) => thread.status === 'completed') ?? [],
    [threads],
  )

  const sortedThreads = useMemo(() => {
    // Trust server cursor order for alphabetical and created sorts. The
    // backend returns deterministic keyset-paginated pages; re-sorting with
    // JS localeCompare or date parsing produces a different comparator than
    // the SQL ORDER BY, causing new pages to interleave into earlier pages
    // and breaking infinite-scroll stability (issue #2452).
    if (sortBy === 'alphabetical' || sortBy === 'created') {
      return activeThreads
    }
    // position: feasible-only ordering — unblocked threads first, then by
    // user-controlled position. Keep the grouping client-side deliberately
    // (introduced via #1644): the backend keyset cursor pages by
    // queue_position only, so blocked rows stay grouped below the unblocked
    // set as pages append. Moving that grouping server-side is explicitly
    // deferred — documented acceptance decision for the position criterion
    // in #2452 rather than silently fighting the cursor with a re-sort.
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
