import { useEffect, useState } from 'react'
import { useInfiniteQuery } from '@tanstack/react-query'
import { queryKeys } from '../query/queryKeys'
import { activityApi, type ActivityPage } from '../services/api-activity'

const DEFAULT_PAGE_SIZE = 50

export function useActivity(pageSize: number = DEFAULT_PAGE_SIZE) {
  const query = useInfiniteQuery({
    queryKey: queryKeys.activity.pages(pageSize),
    queryFn: ({ pageParam }) => activityApi.list(pageParam, pageSize),
    // SAFETY: null is the first page cursor; subsequent pages carry server tokens.
    initialPageParam: null as string | null,
    getNextPageParam: (page: ActivityPage) => page.next_page_token ?? undefined,
  })
  const [hasFailedLoad, setHasFailedLoad] = useState(false)
  useEffect(() => {
    if (query.failureCount > 0) setHasFailedLoad(true)
    else if (query.isSuccess) setHasFailedLoad(false)
  }, [query.failureCount, query.isSuccess])
  return {
    events: query.data?.pages.flatMap((page) => page.events) ?? [],
    isPending: query.isPending,
    isRetrying: query.isPending && hasFailedLoad,
    isError: query.isError,
    error: query.error,
    isLoadingMore: query.isFetchingNextPage,
    hasMore: query.hasNextPage,
    /**
     * True when the current error came from the next-page request rather than
     * the first load or a background refresh. A retry must resume the request
     * that actually failed: `loadMore` for a next-page failure, `refetch` for
     * every other failure (see `useInfiniteCollection.isFetchNextPageError`).
     */
    isFetchNextPageError: query.isFetchNextPageError,
    loadMore: query.fetchNextPage,
    refetch: query.refetch,
  }
}
