import { useEffect, useState } from 'react'
import { useInfiniteQuery } from '@tanstack/react-query'
import { queryKeys } from '../query/queryKeys'
import { activityApi, type ActivityPage } from '../services/api-activity'

export function useActivity() {
  const query = useInfiniteQuery({
    queryKey: queryKeys.activity.pages(),
    queryFn: ({ pageParam }) => activityApi.list(pageParam),
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
    loadMore: query.fetchNextPage,
    refetch: query.refetch,
  }
}
