import { useMemo } from 'react'
import type { Thread } from '../../types'

export type QueueSortBy = 'position' | 'alphabetical' | 'created'

/**
 * Derive the active and completed thread partitions plus the presentation
 * list used by QueuePage and its child modules.
 *
 * The hook owns zero cache and zero query state — it only memoizes derived
 * slices so callers can compose them into presentation modules. It never
 * reorders rows: the backend keyset cursor already encodes the authoritative
 * order, so concatenated pages are displayed exactly as returned. Re-sorting
 * here (by position, localeCompare, or blocked grouping) produced a different
 * comparator than the SQL ORDER BY and let a newly fetched page insert rows
 * ahead of rows already on screen (issue #2566, following #2452).
 *
 * @param threads - All threads returned by the concatenated page query, in
 *   server cursor order.
 * @param _sortBy - Retained sort selector for API compatibility; the server
 *   owns ordering for every sort mode.
 */
export function useQueueFilters(
  threads: Thread[] | null | undefined,
  _sortBy: QueueSortBy,
) {
  const activeThreads = useMemo(
    () => threads?.filter((thread) => thread.status === 'active') ?? [],
    [threads],
  )

  const completedThreads = useMemo(
    () => threads?.filter((thread) => thread.status === 'completed') ?? [],
    [threads],
  )

  // The active list is the displayed order: filtering preserves the server's
  // cursor order, and no client comparator may reshuffle it across pages.
  const sortedThreads = activeThreads
  const filteredThreads = sortedThreads

  return {
    activeThreads,
    completedThreads,
    sortedThreads,
    filteredThreads,
  }
}
