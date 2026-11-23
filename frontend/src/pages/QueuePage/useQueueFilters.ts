import { useMemo } from 'react'
import type { ThreadListItem } from '../../types'

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
  threads: ThreadListItem[] | null | undefined,
  _sortBy: QueueSortBy,
  _searchQuery: string = '',
) {
  const activeThreads = useMemo(
    () => threads?.filter((thread) => thread.status === 'active') ?? [],
    [threads],
  )

  const completedThreads = useMemo(
    () => threads?.filter((thread) => thread.status === 'completed') ?? [],
    [threads],
  )

  // The active list is already the authoritative server-filtered sequence for
  // the same applied search used by filtered_count. Applying String.includes()
  // again here disagrees with SQL ILIKE for wildcard characters and Unicode
  // case folding, which can render an empty list beside a non-zero count.
  // Preserve the returned rows exactly; no client comparator or second filter
  // may reshuffle or remove them across pages (#3614).
  const sortedThreads = activeThreads
  const filteredThreads = sortedThreads

  return {
    activeThreads,
    completedThreads,
    sortedThreads,
    filteredThreads,
  }
}
