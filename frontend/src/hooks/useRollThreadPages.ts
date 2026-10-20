import { useCallback } from 'react'
import { useInfiniteQuery } from '@tanstack/react-query'
import type {
  RollBootstrapThread,
  ThreadExclusionReason,
} from '../types/rollBootstrap'
import type { RollThreadPageApi } from '../services/apiTypes'
import { rollBootstrapApi } from '../services/rollBootstrapApi'
import { queryKeys } from '../query/queryKeys'

/** Matches the backend bootstrap preview (`RollBootstrapResponse.summary_limit`). */
export const ROLL_SECTION_PAGE_SIZE = 20

interface RollSectionPagerOptions {
  /**
   * Number of preview rows the bootstrap already rendered. Page reads start
   * here so the section never re-fetches records the reader can already see.
   */
  startOffset: number
  /** Load pages only while the section is open and counted records remain. */
  enabled: boolean
  pageSize?: number
  api?: RollThreadPageApi
}

export interface RollSectionPager<T> {
  /** Records loaded past the bootstrap preview, in server order. */
  items: T[]
  /** True while a page request is in flight. */
  isFetching: boolean
  isError: boolean
  /** Fetch the next page. No-ops when the server has no further page. */
  loadMore: () => Promise<void>
}

/**
 * Page the blocked-series category beyond the bounded Roll bootstrap preview.
 *
 * The bootstrap reports the accurate `blocked_count` while previewing only the
 * first page, so this hook is how a reader reaches the remaining records
 * (issue #3330). The cursor lives in `pageParam`; the query key stays stable
 * per page size and preview boundary.
 *
 * @param options - Preview boundary, page size, enablement, and injectable API.
 * @returns The loaded records past the preview plus the next-page control.
 */
export function useRollBlockedThreads({
  startOffset,
  enabled,
  pageSize = ROLL_SECTION_PAGE_SIZE,
  api,
}: RollSectionPagerOptions): RollSectionPager<RollBootstrapThread> {
  const client = api ?? rollBootstrapApi
  const query = useInfiniteQuery({
    queryKey: queryKeys.roll.blockedThreads({ pageSize, startOffset }),
    queryFn: ({ pageParam }) => client.getBlockedThreadsPage(pageParam, pageSize),
    initialPageParam: startOffset,
    getNextPageParam: (lastPage) => lastPage.next_offset ?? undefined,
    enabled,
    retry: false,
  })

  const items = (query.data?.pages ?? []).flatMap((page) => page.items)

  const loadMore = useCallback((): Promise<void> => {
    if (!query.hasNextPage || query.isFetchingNextPage) {
      return Promise.resolve()
    }
    return query.fetchNextPage().then(() => undefined)
  }, [query])

  return {
    items,
    isFetching: query.isFetching,
    isError: query.isError,
    loadMore,
  }
}

/**
 * Page the out-of-pool category beyond the bounded Roll bootstrap preview.
 *
 * Same contract as {@link useRollBlockedThreads}, scoped to the series the
 * bootstrap reports as inactive so the page total matches `inactive_count`.
 *
 * @param options - Preview boundary, page size, enablement, and injectable API.
 * @returns The loaded records past the preview plus the next-page control.
 */
export function useRollInactiveThreads({
  startOffset,
  enabled,
  pageSize = ROLL_SECTION_PAGE_SIZE,
  api,
}: RollSectionPagerOptions): RollSectionPager<ThreadExclusionReason> {
  const client = api ?? rollBootstrapApi
  const query = useInfiniteQuery({
    queryKey: queryKeys.roll.inactiveThreads({ pageSize, startOffset }),
    queryFn: ({ pageParam }) => client.getInactiveThreadsPage(pageParam, pageSize),
    initialPageParam: startOffset,
    getNextPageParam: (lastPage) => lastPage.next_offset ?? undefined,
    enabled,
    retry: false,
  })

  const items = (query.data?.pages ?? []).flatMap((page) => page.items)

  const loadMore = useCallback((): Promise<void> => {
    if (!query.hasNextPage || query.isFetchingNextPage) {
      return Promise.resolve()
    }
    return query.fetchNextPage().then(() => undefined)
  }, [query])

  return {
    items,
    isFetching: query.isFetching,
    isError: query.isError,
    loadMore,
  }
}
