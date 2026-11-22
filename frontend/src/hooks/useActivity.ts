import { useEffect, useMemo, useState } from 'react'
import { useInfiniteQuery } from '@tanstack/react-query'
import {
  activityApi as defaultActivityApi,
  ACTIVITY_PAGE_SIZE,
  type ActivityApi,
  type ActivityItem,
  type ActivityPage,
} from '../services/api-activity'
import { queryKeys } from '../query/queryKeys'

function normalizeQueryError(error: unknown, fallbackMessage: string): Error | null {
  if (error == null) return null
  if (error instanceof Error) return error
  return new Error(fallbackMessage)
}

/**
 * Read the authenticated reader's owner-scoped activity stream.
 *
 * The native `GET /api/v2/activity` resource returns logical actions in causal
 * order (a snooze and the roll it caused, one coalesced rating) with a stable
 * cursor. This hook keeps the pages in the order the resource issued them,
 * removes a repeated page boundary row, and remembers a failed first load so
 * the History page can offer in-place recovery (#3429) instead of an
 * indefinite loading splash.
 *
 * @param api - Activity service override for tests; production uses the
 *   registered default transport.
 * @returns The accumulated activity items plus bounded loading state.
 */
export function useActivity(api?: ActivityApi) {
  const activityApi = api ?? defaultActivityApi

  const query = useInfiniteQuery({
    // The cursor lives in `pageParam`, so the whole stream shares one key and
    // a refetch restarts from the first page.
    queryKey: queryKeys.activity.list({ pageSize: ACTIVITY_PAGE_SIZE }),
    queryFn: async ({ pageParam }) => {
      try {
        return await activityApi.list(pageParam)
      } catch (error: unknown) {
        if (error instanceof Error) throw error
        throw new Error(
          pageParam === null ? 'Failed to fetch activity' : 'Failed to load more activity',
        )
      }
    },
    // SAFETY: null is the intentional first pageParam; later pages receive the
    // opaque token the resource issued.
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage: ActivityPage) => lastPage.next_page_token ?? undefined,
  })

  // `refetch()` resets React Query's `failureCount`, so latch the first failure
  // to keep the Retry affordance visible through user-initiated retries until
  // the load actually succeeds (same contract as the session index, #3429).
  const [hasFailedLoad, setHasFailedLoad] = useState(false)
  useEffect(() => {
    if (query.failureCount > 0) {
      setHasFailedLoad(true)
    } else if (query.isSuccess) {
      setHasFailedLoad(false)
    }
  }, [query.failureCount, query.isSuccess])

  return useMemo(
    () => {
      const seenEventIds = new Set<number>()
      const items: ActivityItem[] =
        query.data?.pages
          .flatMap((page) => page.items)
          .filter((item) => {
            if (seenEventIds.has(item.event_id)) return false
            seenEventIds.add(item.event_id)
            return true
          }) ?? []

      return {
        data: items,
        isPending: query.isPending,
        isLoadingMore: query.isFetchingNextPage,
        isError: query.isError,
        error: normalizeQueryError(query.error, 'Failed to fetch activity'),
        hasMore: !!query.hasNextPage,
        loadMore: () => query.fetchNextPage(),
        refetch: query.refetch,
        // True while the initial load is still trying after at least one
        // failure, including user-started retries from the Retry button.
        isRetrying: query.isPending && hasFailedLoad,
      }
    },
    [query, hasFailedLoad],
  )
}
