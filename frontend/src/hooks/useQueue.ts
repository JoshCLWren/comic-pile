import { useCallback } from 'react'
import { keepPreviousData, useInfiniteQuery, useMutation } from '@tanstack/react-query'
import type { QueryClient } from '@tanstack/react-query'
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

/** Queue API surface the movement mutations depend on. */
export type QueueApi = Pick<typeof queueApi, 'moveToPosition' | 'moveToFront' | 'moveToBack' | 'shuffle'>

/** Cache reconciliation run after a queue movement mutation succeeds. */
export type QueueInvalidateFn = (client: QueryClient) => Promise<void>

/** Optional injected dependencies for queue movement mutations. */
export interface QueueMutationDeps {
  /** Injectable queue API subset; defaults to the real service. */
  api?: QueueApi
  /** Injectable cache reconciliation; defaults to `invalidateAfterQueueMovement`. */
  invalidate?: QueueInvalidateFn
}

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
 * @param threadsList - Injectable lazy thread-list loader (defaults to the real service).
 */
export function queueThreadsQueryOptions(
  searchTerm?: string,
  sort: QueueSortBy = 'position',
  threadsList: Pick<typeof threadsApi, 'list'> = threadsApi,
) {
  const normalizedSearch = searchTerm?.trim() || undefined
  const apiSort = toApiSort(sort)

  return {
    // SAFETY: queueThreadsQueryOptions only receives canonical QueueSort values from the UI selector.
    queryKey: queryKeys.queue.list({ search: normalizedSearch, sort: sort as QueueSort, pageSize: QUEUE_PAGE_SIZE }),
    queryFn: ({ pageParam }: { pageParam: string | null }) =>
      threadsList.list(
        {
          ...(normalizedSearch ? { search: normalizedSearch } : {}),
          sort: apiSort,
          ...(pageParam ? {} : { page_size: QUEUE_PAGE_SIZE }),
        },
        pageParam ?? undefined,
      ),
    // SAFETY: null is the intentional first pageParam; useInfiniteQuery types it as string after the first page.
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage: ThreadListResponse) => lastPage.next_page_token ?? undefined,
    /**
     * Keep previously rendered queue rows on screen while a search/sort key
     * transition fetches its first page. Without this the changing key resets
     * the infinite query to an empty pending state, so the Queue page tears
     * down the list and flashes the full-screen loader on every search commit.
     * `keepPreviousData` exposes the old rows as placeholder data until the new
     * first page arrives.
     */
    placeholderData: keepPreviousData,
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
 * @param threadsList - Injectable lazy thread-list loader (defaults to the real service).
 */
export function useQueueThreads(
  searchTerm?: string,
  sort: QueueSortBy = 'position',
  threadsList: Pick<typeof threadsApi, 'list'> = threadsApi,
) {
  const query = useInfiniteQuery({
    ...queueThreadsQueryOptions(searchTerm, sort, threadsList),
    retry: false,
    placeholderData: keepPreviousData,
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

/**
 * Moves a thread to an explicit queue position and reconciles queue-owned
 * read models.
 *
 * @param deps - Optional injected queue API and cache-invalidation seam.
 */
export function useMoveToPosition(deps: QueueMutationDeps = {}) {
  const { api = queueApi, invalidate = invalidateAfterQueueMovement } = deps
  const mutation = useMutation({
    mutationFn: async ({ id, position }: MoveToPositionPayload) => {
      await api.moveToPosition(id, position)
      await invalidate(queryClient)
    },
    onError: (error) => {
      console.error('Failed to move thread to position:', getApiErrorDetail(error))
    },
  })

  return {
    mutate: mutation.mutateAsync,
    isPending: mutation.isPending,
    isError: mutation.isError,
  }
}

/**
 * Moves a thread to the front of the queue and reconciles queue-owned read
 * models.
 *
 * @param deps - Optional injected queue API and cache-invalidation seam.
 */
export function useMoveToFront(deps: QueueMutationDeps = {}) {
  const { api = queueApi, invalidate = invalidateAfterQueueMovement } = deps
  const mutation = useMutation({
    mutationFn: async (id: number) => {
      await api.moveToFront(id)
      await invalidate(queryClient)
    },
    onError: (error) => {
      console.error('Failed to move thread to front:', getApiErrorDetail(error))
    },
  })

  return {
    mutate: mutation.mutateAsync,
    isPending: mutation.isPending,
    isError: mutation.isError,
  }
}

/**
 * Moves a thread to the back of the queue and reconciles queue-owned read
 * models.
 *
 * @param deps - Optional injected queue API and cache-invalidation seam.
 */
export function useMoveToBack(deps: QueueMutationDeps = {}) {
  const { api = queueApi, invalidate = invalidateAfterQueueMovement } = deps
  const mutation = useMutation({
    mutationFn: async (id: number) => {
      await api.moveToBack(id)
      await invalidate(queryClient)
    },
    onError: (error) => {
      console.error('Failed to move thread to back:', getApiErrorDetail(error))
    },
  })

  return {
    mutate: mutation.mutateAsync,
    isPending: mutation.isPending,
    isError: mutation.isError,
  }
}

/**
 * Shuffles the queue and reconciles queue-owned read models.
 *
 * @param deps - Optional injected queue API and cache-invalidation seam.
 */
export function useShuffleQueue(deps: QueueMutationDeps = {}) {
  const { api = queueApi, invalidate = invalidateAfterQueueMovement } = deps
  const mutation = useMutation({
    mutationFn: async () => {
      await api.shuffle()
      await invalidate(queryClient)
    },
    onError: (error) => {
      console.error('Failed to shuffle queue:', getApiErrorDetail(error))
    },
  })

  return {
    mutate: mutation.mutateAsync,
    isPending: mutation.isPending,
    isError: mutation.isError,
  }
}

// Re-export delete thread hook for backward compatibility
export { useDeleteThread } from './useThread';
