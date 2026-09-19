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
  getNextPageParam: (lastPage: TPage) => TToken | null | undefined
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
}

/** Semantic state exposed by the canonical paginator. */
export interface InfiniteCollectionState<TItem, TPage, TToken = PageToken> {
  /** All items across every loaded page, in server order. */
  items: TItem[]
  /** The raw pages currently cached. */
  pages: TPage[]
  /** True while the first page is loading and no data is available yet. */
  isInitialLoading: boolean
  /** True while an additional cursor page is being appended. */
  isNextPageLoading: boolean
  /** True while any fetch is in flight (initial, refetch, or next page). */
  isLoading: boolean
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
  isError: boolean
  error: unknown
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
  const query = useInfiniteQuery({
    queryKey: spec.queryKey,
    queryFn: spec.queryFn,
    initialPageParam: spec.initialPageParam,
    getNextPageParam: spec.getNextPageParam,
    enabled: spec.enabled,
    retry: spec.retry,
    placeholderData: spec.placeholderData,
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
  const nextPageToken: TToken | null =
    hasNextPage && lastPage ? (spec.getNextPageParam(lastPage) ?? null) : null

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
    pages,
    isInitialLoading,
    isNextPageLoading,
    isLoading: query.isFetching,
    isPending: isInitialLoading || isNextPageLoading,
    hasNextPage,
    nextPageToken,
    fetchNextPage,
    refetch,
    isError: query.isError,
    error: query.error,
  }
}