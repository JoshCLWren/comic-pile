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
  /**
   * Token identifying the category state the preview was read against. Cached
   * pages belong to that state, so a changed category reads fresh pages
   * instead of appending rows the refreshed preview already shows.
   */
  revision: string
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
 * Build the token that binds cached pages to the category state they describe.
 *
 * A page read continues after the bootstrap preview, so the two only line up
 * while the category itself is unchanged. The token changes whenever the
 * counted total or the previewed membership changes, which is exactly when the
 * cached pages would describe a category the reader no longer sees.
 *
 * @param count - Authoritative category total reported by the bootstrap.
 * @param previewIds - Identity of each previewed row, in server order.
 * @returns A stable token for the category state.
 */
export function rollSectionRevision(count: number, previewIds: number[]): string {
  return `${count}:${previewIds.join(',')}`
}

/**
 * Page the blocked-series category beyond the bounded Roll bootstrap preview.
 *
 * The bootstrap reports the accurate `blocked_count` while previewing only the
 * first page, so this hook is how a reader reaches the remaining records
 * (issue #3330). The cursor lives in `pageParam`; the query key stays stable
 * per page size, preview boundary, and category revision.
 *
 * @param options - Preview boundary, category revision, page size, enablement,
 *   and injectable API.
 * @returns The loaded records past the preview plus the next-page control.
 */
export function useRollBlockedThreads({
  startOffset,
  revision,
  enabled,
  pageSize = ROLL_SECTION_PAGE_SIZE,
  api,
}: RollSectionPagerOptions): RollSectionPager<RollBootstrapThread> {
  const client = api ?? rollBootstrapApi
  const query = useInfiniteQuery({
    queryKey: queryKeys.roll.blockedThreads({ pageSize, startOffset, revision }),
    queryFn: ({ pageParam }) => client.getBlockedThreadsPage(pageParam, pageSize),
    initialPageParam: startOffset,
    getNextPageParam: (lastPage) => lastPage.next_offset ?? undefined,
    enabled,
    retry: false,
  })

  const items = (query.data?.pages ?? []).flatMap((page) => page.items)

  const loadMore = useCallback((): Promise<void> => {
    if (query.isFetchingNextPage) {
      return Promise.resolve()
    }
    // A failed first page leaves the infinite query without data, so
    // `hasNextPage` is false and the ordinary path would never make a request
    // again. Retry that first read instead, so the reader can recover.
    if (!query.data) {
      return query.refetch().then(() => undefined)
    }
    if (!query.hasNextPage) {
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
 * @param options - Preview boundary, category revision, page size, enablement,
 *   and injectable API.
 * @returns The loaded records past the preview plus the next-page control.
 */
export function useRollInactiveThreads({
  startOffset,
  revision,
  enabled,
  pageSize = ROLL_SECTION_PAGE_SIZE,
  api,
}: RollSectionPagerOptions): RollSectionPager<ThreadExclusionReason> {
  const client = api ?? rollBootstrapApi
  const query = useInfiniteQuery({
    queryKey: queryKeys.roll.inactiveThreads({ pageSize, startOffset, revision }),
    queryFn: ({ pageParam }) => client.getInactiveThreadsPage(pageParam, pageSize),
    initialPageParam: startOffset,
    getNextPageParam: (lastPage) => lastPage.next_offset ?? undefined,
    enabled,
    retry: false,
  })

  const items = (query.data?.pages ?? []).flatMap((page) => page.items)

  const loadMore = useCallback((): Promise<void> => {
    if (query.isFetchingNextPage) {
      return Promise.resolve()
    }
    // A failed first page leaves the infinite query without data, so
    // `hasNextPage` is false and the ordinary path would never make a request
    // again. Retry that first read instead, so the reader can recover.
    if (!query.data) {
      return query.refetch().then(() => undefined)
    }
    if (!query.hasNextPage) {
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
