import { useIsFetching } from '@tanstack/react-query'
import { queryKeys } from '../../query/queryKeys'

/**
 * True while the Queue list is fetching any page.
 *
 * The Queue loader keeps previously loaded rows on screen through
 * `keepPreviousData` while a new search key loads (see `useQueueThreads`).
 * Those rows are filtered client-side for the new term, so an empty filtered
 * list during that window does not mean "no match" yet — it means the matching
 * page has not arrived (issue #3912). Reading the cache's fetch status here lets
 * the list show a loading state instead of a false zero-match result.
 *
 * The filter is the canonical `queue.pages` key prefix, so it ignores the
 * search-independent active-count query and every unrelated fetch.
 *
 * Returns:
 *   True while any Queue page query has a fetch in flight.
 */
export function useQueueListLoading(): boolean {
  return useIsFetching({ queryKey: queryKeys.queue.pages() }) > 0
}
