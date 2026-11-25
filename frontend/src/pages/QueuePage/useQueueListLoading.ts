import { useIsFetching } from '@tanstack/react-query'
import type { QueryKey } from '@tanstack/react-query'

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
 * @param queryKey - Exact canonical key for the currently applied Queue page.
 * @returns True while the matching Queue page query is in flight.
 */
export function useQueueListLoading(queryKey: QueryKey): boolean {
  return useIsFetching({ queryKey, exact: true }) > 0
}
