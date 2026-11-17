import { useInfiniteCollection } from '../pagination'
import { queryKeys } from '../query/queryKeys'
import { threadsApi } from '../services/api-threads'
import type { ThreadListItem, ThreadListResponse } from '../types'

/** The finished shelf has its own cursor, independent of the active Queue. */
export const COMPLETED_PAGE_SIZE = 50

/**
 * Discover finished series with one bounded page, then fetch additional pages
 * only when the reader expands the shelf and requests more. In particular,
 * never attempt to derive finished rows from the active-only Queue response.
 *
 * The backend does not expose a completed total: consumers must display the
 * loaded count as a lower bound while a continuation cursor remains.
 */
export function useCompletedThreads(
  enabled = true,
  api: Pick<typeof threadsApi, 'listCompleted'> = threadsApi,
) {
  const query = useInfiniteCollection<ThreadListItem, ThreadListResponse>({
    queryKey: queryKeys.completed.list({ sort: 'created', pageSize: COMPLETED_PAGE_SIZE }),
    queryFn: ({ pageParam }) =>
      api.listCompleted(undefined, 'created', pageParam ?? undefined, COMPLETED_PAGE_SIZE),
    initialPageParam: null,
    getNextPageParam: (page) => page.next_page_token ?? undefined,
    selectPage: (page) => page.threads,
    selectId: (thread) => thread.id,
    enabled,
    retry: false,
  })

  return {
    threads: query.items,
    hasNextPage: query.hasNextPage,
    isLoadingMore: query.isNextPageLoading,
    isLoading: query.isLoading,
    isError: query.isError,
    loadMore: query.fetchNextPage,
    // A failed continuation page is not part of refetch's loaded-page set.
    // Retry the missing cursor rather than silently reloading page one.
    retry: query.isFetchNextPageError ? query.fetchNextPage : query.refetch,
  }
}
