import { useMemo } from 'react'
import type { Thread } from '../../types'

export type QueueSortBy = 'position' | 'alphabetical' | 'created'

/**
 * Derive the active and completed thread partitions plus the search/sort
 * filtered presentation list used by QueuePage and its child modules.
 *
 * The hook owns zero cache and zero query state — it only memoizes
 * derived slices so callers can compose them into presentation modules.
 *
 * @param threads - All threads returned by the current page query, in any order.
 * @param searchQuery - Raw search box input. Empty/whitespace = no filter.
 * @param sortBy - Sort selector; defaults to queue position.
 */
export function useQueueFilters(
  threads: Thread[] | null | undefined,
  searchQuery: string,
  sortBy: QueueSortBy,
) {
  const activeThreads = useMemo(
    () =>
      threads
        ?.filter((thread) => thread.status === 'active')
        .sort((a, b) => a.queue_position - b.queue_position) ?? [],
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
    return activeThreads
  }, [activeThreads, sortBy])

  const filteredThreads = useMemo(() => {
    const trimmed = searchQuery.trim()
    if (!trimmed) return sortedThreads
    const needle = trimmed.toLowerCase()
    return sortedThreads.filter((t) => t.title.toLowerCase().includes(needle))
  }, [sortedThreads, searchQuery])

  return {
    activeThreads,
    completedThreads,
    sortedThreads,
    filteredThreads,
  }
}
