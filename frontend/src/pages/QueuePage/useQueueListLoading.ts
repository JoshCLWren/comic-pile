import { useIsFetching } from '@tanstack/react-query'
import { QUEUE_PAGE_SIZE } from '../../hooks/useQueue'
import type { QueueSortBy } from './useQueueFilters'
import { queryKeys } from '../../query/queryKeys'

/**
 * True while the currently applied Queue page query is fetching.
 *
 * The Queue loader keeps previously loaded rows available through
 * `keepPreviousData` while a new search key loads. QueuePage hides those
 * previous-key rows and uses this flag to distinguish loading from a settled
 * zero-match. Only the current search/sort key owns that presentation state:
 * an older request that settles late must not keep a newer zero-result view
 * stuck on "Loading" (#3614).
 *
 * @param searchTerm - Currently applied Queue search term.
 * @param sort - Currently applied Queue sort order.
 * @returns True while the matching Queue page query is in flight.
 */
export function useQueueListLoading(
  searchTerm?: string,
  sort: QueueSortBy = 'position',
): boolean {
  return useIsFetching({
    queryKey: queryKeys.queue.list({ search: searchTerm, sort, pageSize: QUEUE_PAGE_SIZE }),
  }) > 0
}
