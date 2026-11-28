import { useCallback } from 'react'
import { useInfiniteQuery, keepPreviousData } from '@tanstack/react-query'
import type { QueryFunctionContext, QueryKey, InfiniteData, PlaceholderDataFunction, UseInfiniteQueryOptions } from '@tanstack/react-query'

/** Opaque cursor token for the canonical pagination contract. */
export type PageToken = string | null

/**
 * Specification for the canonical TanStack paginator.
 *
 * The data mechanism is independent of the trigger that advances it: an
 * automatic intersection sentinel and an explicit Load More button both call
 * `fetchNextPage` from the same hook, so a collection never implements two
 * different pagination paths.
 *
 * Consumers select page payloads into the flat item list with `selectPage`
 * and may pass `selectId` to deduplicate items across page boundaries (for
 * example when the server can repeat the last row). The opaque cursor lives
 * in `pageParam`, never in the query key.
 */
export interface InfiniteCollectionSpec<TItem, TPage, TToken = PageToken> {
  /** Canonical query key (cursor excluded; changing filters/sort resets the page). */
  queryKey: QueryKey
  /** Fetches one page; `pageParam` is `initialPageParam` on the first page, then an opaque cursor. */
  queryFn: (context: QueryFunctionContext<QueryKey, TToken>) => Promise<TPage>
  /** First-page cursor value (usually `null`). */
  initialPageParam: TToken
  /** Reads the opaque next-page cursor from a page; `null`/`undefined` means no more pages. */
  getNextPageParam: (lastPage: TPage, allPages: TPage[]) => TToken | null | undefined
  /** Maps a page payload to its flat list of items. */
  selectPage: (page: TPage) => TItem[]
  /** Optional item identity used to deduplicate rows that repeat across page boundaries. */
  selectId?: (item: TItem) => string | number
  /** Whether the paginator should run at all (mirrors `useInfiniteQuery` `enabled`). */
  enabled?: boolean
  /** Failure retry policy (mirrors `useInfiniteQuery` `retry`). */
  retry?: boolean | number
  /** Placeholder data policy such as `keepPreviousData` (mirrors `useInfiniteQuery`). */
  placeholderData?: InfiniteData<TPage, TToken> | PlaceholderDataFunction<InfiniteData<TPage, TToken>, Error, InfiniteData<TPage, TToken>, readonly unknown[]> | typeof keepPreviousData
  /** Refetch on window focus policy (mirrors `useInfiniteQuery`). */
  refetchOnWindowFocus?: boolean | 'always'
  /** Freshness window (mirrors `useInfiniteQuery`). */
  staleTime?: number
  /** Garbage-collection window (mirrors `useInfiniteQuery`). */
  gcTime?: number
}

/** Semantic state exposed by the canonical paginator. */
export interface InfiniteCollectionState<TItem, TPage, TToken = PageToken> {
  /** All items across every loaded page, in server order. */
  items: TItem[]
  /** The raw infinite cache entry, for consumers that expose page payloads. */
  data: InfiniteData<TPage, TToken> | undefined
  /** The raw pages currently cached. */
  pages: TPage[]
  /** True while the first page is loading and no data is available yet. */
  isInitialLoading: boolean
  /** True while an additional cursor page is being appended. */
  isNextPageLoading: boolean
  /** Alias for `isNextPageLoading` for TanStack-shaped call sites. */
  isFetchingNextPage: boolean
  /** True while any fetch is in flight (initial, refetch, or next page). */
  isLoading: boolean
  /** Alias for `isLoading` used by callers that render a fetching affordance. */
  isFetching: boolean
  /** Consecutive failure count, used by callers that latch a first-load error. */
  failureCount: number
  /** True once the current query key has a successful response. */
  isSuccess: boolean
  /** TanStack fetch status (`idle`, `fetching`, or `paused`). */
  fetchStatus: 'idle' | 'fetching' | 'paused'
  /**
   * True when the rendered pages are placeholder data kept from the previous
   * query key by `keepPreviousData` while the new key's first page loads.
   * Surfaces must not present placeholder-derived numbers (totals, counts) as
   * the answer for the current filter state (#3614).
   */
  isPlaceholderData: boolean
  /**
   * Convenience flag matching the previous Queue semantics: loading the first
   * page OR appending another page while already-rendered rows stay visible.
   */
  isPending: boolean
  /** True when another page exists according to the last `next_page_token`. */
  hasNextPage: boolean
  /** The opaque cursor for the next fetchable page, or `null` at the end. */
  nextPageToken: TToken | null
  /** Appends the next page; a safe no-op when there is nothing to fetch. */
  fetchNextPage: () => Promise<void>
  /** Refetches the current pages (retry path for failed loads). */
  refetch: () => Promise<void>
  /**
   * True when the current error came from a next-page request rather than from
   * the first page or a background refresh. A retry must resume the request
   * that actually failed: the missing next page for a next-page error, and a
   * refetch for every other error.
   */
  isFetchNextPageError: boolean
  isError: boolean
  error: Error | null
}

/**
 * The one canonical TanStack pagination hook for user-facing collections.
 *
 * It exposes semantic state (`items`, initial-loading, next-page-loading,
 * `hasNextPage`, `fetchNextPage`, error/refetch) so upstream surfaces never
 * reach into TanStack page internals, and it is agnostic to what triggers the
 * next page: an intersection sentinel or a Load More button.
 */
export function useInfiniteCollection<TItem, TPage, TToken = PageToken>(
  spec: InfiniteCollectionSpec<TItem, TPage, TToken>,
): InfiniteCollectionState<TItem, TPage, TToken> {
  // Repeated or stale tokens are a shared-paginator concern: a consumer must
  // never re-request a cursor that was already used to fetch an earlier page.
  // Compare against the actual page params (not recomputed cursors) so the
  // guard works for both opaque tokens and documented offset cursors.
  const resolveNextToken = (
    lastPage: TPage | undefined,
    allPages: TPage[],
    usedParams: TToken[],
  ): TToken | undefined => {
    if (!lastPage) return undefined
    const next = spec.getNextPageParam(lastPage, allPages)
    if (next == null) return undefined
    for (const used of usedParams) {
      if (used != null && Object.is(used, next)) return undefined
    }
    return next
  }

  const query = useInfiniteQuery<TPage, Error, InfiniteData<TPage, TToken>, QueryKey, TToken>({
    queryKey: spec.queryKey,
    queryFn: spec.queryFn,
    initialPageParam: spec.initialPageParam,
    getNextPageParam: (lastPage, allPages, _lastPageParam, allPageParams) =>
      resolveNextToken(lastPage, allPages as TPage[], allPageParams),
    enabled: spec.enabled,
    retry: spec.retry,
    placeholderData: spec.placeholderData,
    refetchOnWindowFocus: spec.refetchOnWindowFocus,
    staleTime: spec.staleTime,
    gcTime: spec.gcTime,
  })

  const pages = query.data?.pages ?? []
  const lastPage = pages[pages.length - 1] ?? null

  const selectedItems = pages.flatMap(spec.selectPage)
  let items = selectedItems
  if (spec.selectId) {
    const seen = new Set<string | number>()
    items = selectedItems.filter((item) => {
      const id = spec.selectId!(item)
      if (seen.has(id)) return false
      seen.add(id)
      return true
    })
  }

  const hasNextPage = !!query.hasNextPage
  const nextPageToken: TToken | null = hasNextPage && lastPage
    ? (resolveNextToken(lastPage, pages, query.data?.pageParams ?? []) ?? null)
    : null

  const fetchNextPage = useCallback(async (): Promise<void> => {
    if (!query.hasNextPage || query.isFetchingNextPage) {
      return
    }
    await query.fetchNextPage()
  }, [query])

  const refetch = useCallback(async (): Promise<void> => {
    await query.refetch()
  }, [query])

  const isInitialLoading = query.isPending
  const isNextPageLoading = query.isFetchingNextPage

  return {
    items,
    data: query.data,
    pages,
    isInitialLoading,
    isNextPageLoading,
    isFetchingNextPage: query.isFetchingNextPage,
    isLoading: query.isFetching,
    isFetching: query.isFetching,
    failureCount: query.failureCount,
    isSuccess: query.isSuccess,
    fetchStatus: query.fetchStatus,
    isPlaceholderData: query.isPlaceholderData,
    isPending: isInitialLoading || isNextPageLoading,
    hasNextPage,
    nextPageToken,
    fetchNextPage,
    refetch,
    isFetchNextPageError: query.isFetchNextPageError,
    isError: query.isError,
    error: query.error,
  }
}