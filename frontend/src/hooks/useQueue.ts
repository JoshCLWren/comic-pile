import { useCallback, useState } from 'react'
import { useInfiniteQuery } from '@tanstack/react-query'
import { invalidateAfterQueueMovement } from '../query/cacheEffects'
import { queryClient } from '../query/queryClient'
import { queryKeys } from '../query/queryKeys'
import { queueApi, threadsApi } from '../services/api'
import { getApiErrorDetail } from '../utils/apiError'
import type { MoveToPositionPayload, Thread, ThreadListResponse } from '../types'
import type { QueueSortBy } from '../pages/QueuePage/useQueueFilters'
import type { QueueSort } from '../query/queryKeys'

/** Bounded initial page size for Queue. The cursor (`next_page_token`) drives
 * every subsequent page, so later pages never need an explicit page_size. */
export const QUEUE_PAGE_SIZE = 50

type ApiSort = 'position' | 'title' | 'created'

function toApiSort(sort: QueueSortBy): ApiSort {
  // The backend cursor contract uses `title` for the alphabetical order.
  return sort === 'alphabetical' ? 'title' : sort
}

/**
 * Canonical bounded Queue list query options: the documented `queue.pages`
 * key plus the exact first-page fetch contract consumed by
 * `useInfiniteQuery` in `useQueueThreads`.
 *
 * Sharing this factory keeps speculative warm-up (route prefetch) and the
 * live screen on one contract, so a warmed first page is read by the Queue
 * screen instead of hydrating a cache no consumer reads.
 *
 * @param searchTerm - Retained search filter; empty string means no filter.
 * @param sort - Retained sort order; drives the server-side deterministic cursor.
 */
export function queueThreadsQueryOptions(searchTerm?: string, sort: QueueSortBy = 'position') {
  const normalizedSearch = searchTerm?.trim() || undefined
  const apiSort = toApiSort(sort)

  return {
    queryKey: queryKeys.queue.list({ search: normalizedSearch, sort: sort as QueueSort, pageSize: QUEUE_PAGE_SIZE }),
    queryFn: ({ pageParam }: { pageParam: string | null }) =>
      threadsApi.list(
        {
          ...(normalizedSearch ? { search: normalizedSearch } : {}),
          sort: apiSort,
          ...(pageParam ? {} : { page_size: QUEUE_PAGE_SIZE }),
        },
        pageParam ?? undefined,
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage: ThreadListResponse) => lastPage.next_page_token ?? undefined,
  }
}

/**
 * Bounded, incremental Queue loader built on TanStack Query's infinite query
 * and the canonical `queue.pages` query key.
 *
 * The first navigation requests exactly one bounded page. Later pages are
 * appended only through `loadMore` (driven by the `next_page_token` cursor),
 * never by automatic traversal. Changing `searchTerm` or `sort` changes the
 * query key, which resets the loader to the first compatible page.
 *
 * @param searchTerm - Retained search filter; empty string means no filter.
 * @param sort - Retained sort order; drives the server-side deterministic cursor.
 */
export function useQueueThreads(searchTerm?: string, sort: QueueSortBy = 'position') {
  const query = useInfiniteQuery({
    ...queueThreadsQueryOptions(searchTerm, sort),
    retry: false,
  })

  const data = query.data?.pages.flatMap((page) => page.threads) ?? null
  // Initial load OR an in-flight next-page append both keep already-rendered
  // rows visible: `isPending` drives the full-screen loader only before any
  // data exists, while `isFetchingNextPage` drives the inline loading indicator.
  const isPending = query.isPending || query.isFetchingNextPage
  const isError = query.isError
  const lastPage = query.data?.pages.at(-1)
  const nextPageToken = query.hasNextPage ? (lastPage?.next_page_token ?? null) : null

  const refetch = useCallback((): Promise<void> => {
    return query.refetch().then(() => undefined)
  }, [query])

  const loadMore = useCallback((): Promise<void> => {
    if (!query.hasNextPage || query.isFetchingNextPage) {
      return Promise.resolve()
    }
    return query.fetchNextPage().then(() => undefined)
  }, [query])

  return { data, isPending, isError, refetch, nextPageToken, loadMore }
}

export function useMoveToPosition() {
  const [isPending, setIsPending] = useState(false)
  const [isError, setIsError] = useState(false)

  const mutate = useCallback(async ({ id, position }: MoveToPositionPayload) => {
    try {
      setIsPending(true)
      setIsError(false)
      await queueApi.moveToPosition(id, position)
      await invalidateAfterQueueMovement(queryClient)
    } catch (error: unknown) {
      setIsError(true)
      console.error('Failed to move thread to position:', getApiErrorDetail(error))
      throw error
    } finally {
      setIsPending(false)
    }
  }, [])

  return { mutate, isPending, isError }
}

export function useMoveToFront() {
  const [isPending, setIsPending] = useState(false)
  const [isError, setIsError] = useState(false)

  const mutate = useCallback(async (id: number) => {
    try {
      setIsPending(true)
      setIsError(false)
      await queueApi.moveToFront(id)
      await invalidateAfterQueueMovement(queryClient)
    } catch (error: unknown) {
      setIsError(true)
      console.error('Failed to move thread to front:', getApiErrorDetail(error))
      throw error
    } finally {
      setIsPending(false)
    }
  }, [])

  return { mutate, isPending, isError }
}

export function useMoveToBack() {
  const [isPending, setIsPending] = useState(false)
  const [isError, setIsError] = useState(false)

  const mutate = useCallback(async (id: number) => {
    try {
      setIsPending(true)
      setIsError(false)
      await queueApi.moveToBack(id)
      await invalidateAfterQueueMovement(queryClient)
    } catch (error: unknown) {
      setIsError(true)
      console.error('Failed to move thread to back:', getApiErrorDetail(error))
      throw error
    } finally {
      setIsPending(false)
    }
  }, [])

  return { mutate, isPending, isError }
}

export function useShuffleQueue() {
  const [isPending, setIsPending] = useState(false)
  const [isError, setIsError] = useState(false)

  const mutate = useCallback(async () => {
    try {
      setIsPending(true)
      setIsError(false)
      await queueApi.shuffle()
      await invalidateAfterQueueMovement(queryClient)
    } catch (error: unknown) {
      setIsError(true)
      console.error('Failed to shuffle queue:', getApiErrorDetail(error))
      throw error
    } finally {
      setIsPending(false)
    }
  }, [])

  return { mutate, isPending, isError }
}

// Re-export delete thread hook for backward compatibility
export { useDeleteThread } from './useThread';
