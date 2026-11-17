import { useEffect, useMemo, useState } from 'react'
import { useInfiniteQuery } from '@tanstack/react-query'
import { activityApi as defaultActivityApi } from '../services/api-activity'
import type { ActivityApi } from '../services/apiTypes'
import type { ActivityResponse, ActivityEvent } from '../types'
import { queryKeys } from '../query/queryKeys'

const DEFAULT_PAGE_SIZE = 50

/**
 * Normalizes an activity response by flattening the infinite data structure
 * and deduplicating events that might appear across pages.
 */
function normalizeActivityData(data: ActivityResponse[] | undefined): ActivityEvent[] {
  if (!data || data.length === 0) return []
  
  const seenIds = new Set<number>()
  const events: ActivityEvent[] = []
  
  // Process in reverse order (oldest first) to maintain chronological order
  for (const page of [...data].reverse()) {
    for (const event of page.events) {
      if (!seenIds.has(event.event_id)) {
        seenIds.add(event.event_id)
        events.push(event)
      }
    }
  }
  
  return events.reverse() // Return in reverse chronological order (newest first)
}

/**
 * Hook for fetching the owner-scoped activity timeline.
 * 
 * This replaces the Python `GET /api/v1/sessions/` endpoint for the History page
 * to fix the omission of sessionless snoozes and ratings described in issue #4822.
 * 
 * @param api - Optional activity API instance (defaults to the default singleton)
 * @returns The activity data, loading state, and pagination controls
 */
export function useActivity(api?: ActivityApi) {
  const activity = api ?? defaultActivityApi
  
  const query = useInfiniteQuery({
    queryKey: queryKeys.activity.list({ pageSize: DEFAULT_PAGE_SIZE }),
    queryFn: async ({ pageParam }) => {
      try {
        // Handle cursor token: if provided, use it; otherwise start from beginning
        const cursorToken = pageParam ? String(pageParam) : null
        return await activity.list(cursorToken, DEFAULT_PAGE_SIZE)
      } catch (error: unknown) {
        if (error instanceof Error) {
          throw error
        }
        throw new Error('Failed to fetch activity timeline')
      }
    },
    // SAFETY: null is the intentional first pageParam; later pages always receive page tokens.
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage: ActivityResponse) => lastPage.next_page_token ?? undefined,
  })

  // `refetch()` resets React Query's `failureCount` to 0, so keying the bounded
  // loading state on `failureCount` alone would drop the History page back to the
  // bare loading splash the instant someone presses Retry, which is the
  // frozen-splash symptom issue #3429 exists to remove. Latch the first failure
  // so the affordance survives user-initiated retries until the load succeeds.
  const [hasFailedLoad, setHasFailedLoad] = useState(false)
  useEffect(() => {
    if (query.failureCount > 0) {
      setHasFailedLoad(true)
    } else if (query.isSuccess) {
      setHasFailedLoad(false)
    }
  }, [query.failureCount, query.isSuccess])

  const events = useMemo(() => normalizeActivityData(query.data?.pages), [query.data?.pages])

  return {
    events,
    isPending: query.isPending,
    isError: query.isError,
    error: query.error instanceof Error 
      ? query.error 
      : query.error 
        ? new Error('Failed to fetch activity timeline') 
        : null,
    // True while the initial load is still trying after at least one failure,
    // including the retries a user starts from the Retry affordance. Keyed on
    // isPending (already observed) rather than isFetching so the retry
    // affordance never adds a new render subscription of its own.
    isRetrying: query.isPending && hasFailedLoad,
    refetch: query.refetch,
    // Pagination
    isLoadingMore: query.isFetchingNextPage,
    hasMore: !!query.hasNextPage,
    loadMore: () => query.fetchNextPage(),
  }
}