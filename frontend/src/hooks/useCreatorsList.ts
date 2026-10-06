import { useCallback } from 'react'
import { useInfiniteQuery } from '@tanstack/react-query'
import { creatorsApi } from '../services/api-creators'
import type { CreatorListItem, CreatorListResponse } from '../services/api-creators'
import { queryKeys } from '../query/queryKeys'

/** Bounded page size for the personal creator browse list (backend max is 50). */
export const CREATOR_LIST_PAGE_SIZE = 20

/** Lower bound of the personal 0-5 average-rating filter. */
export const CREATOR_RATING_MIN = 0

/** Upper bound of the personal 0-5 average-rating filter. */
export const CREATOR_RATING_MAX = 5

/** Server-side browse orderings exposed by `GET /api/v1/creators`. */
export type CreatorListSort = 'name' | 'ratings_count' | 'average_rating'

/** Normalized browse selection; a blank search is stored as `undefined`. */
export interface CreatorListSelection {
  search?: string
  sort?: CreatorListSort
  limit?: number
  minRatings?: number
  role?: string
  minRating?: number
  maxRating?: number
  hasUnreadWork?: boolean
}

type CreatorsListApi = Pick<typeof creatorsApi, 'getList'>

/**
 * Keep an average-rating filter only when it is a real number on the personal
 * 0-5 scale, so query keys stay canonical and the wire request never carries a
 * value the backend would reject.
 */
function normalizeRatingFilter(value: number | undefined): number | undefined {
  if (value === undefined || Number.isNaN(value)) return undefined
  if (value < CREATOR_RATING_MIN || value > CREATOR_RATING_MAX) return undefined
  return value
}

/**
 * Canonical bounded creator discovery query options: the documented
 * `creators.list` key plus the exact first-page fetch contract consumed by
 * `useCreatorsList`.
 *
 * Every bounded filter is part of the key, so changing a filter starts a fresh
 * collection at offset 0 instead of appending to pages produced under the
 * previous selection.
 *
 * The backend serves a `limit`/`offset` page, so the opaque cursor is the next
 * row offset and it lives in `pageParam`, never in the key. A page that returns
 * no rows always ends the collection, which keeps the "load more" trigger from
 * spinning on a short or filtered page.
 */
export function creatorListQueryOptions(
  selection: CreatorListSelection,
  listApi: CreatorsListApi = creatorsApi,
) {
  const search = selection.search?.trim() || undefined
  const sort = selection.sort ?? 'name'
  const limit = selection.limit ?? CREATOR_LIST_PAGE_SIZE
  const minRatings =
    selection.minRatings !== undefined && selection.minRatings > 0
      ? selection.minRatings
      : undefined
  const role = selection.role?.trim() || undefined
  const minRating = normalizeRatingFilter(selection.minRating)
  const maxRating = normalizeRatingFilter(selection.maxRating)
  const hasUnreadWork = selection.hasUnreadWork ?? undefined

  return {
    queryKey: queryKeys.creators.list({
      search,
      sort,
      limit,
      minRatings,
      role,
      minRating,
      maxRating,
      hasUnreadWork,
    }),
    queryFn: ({ pageParam }: { pageParam: number }) =>
      listApi.getList({
        search,
        sort,
        limit,
        offset: pageParam,
        min_ratings: minRatings,
        role,
        min_rating: minRating,
        max_rating: maxRating,
        has_unread_work: hasUnreadWork,
      }),
    initialPageParam: 0,
    getNextPageParam: (lastPage: CreatorListResponse) => {
      if (lastPage.items.length === 0) return undefined
      const nextOffset = lastPage.offset + lastPage.items.length
      return nextOffset < lastPage.total ? nextOffset : undefined
    },
  }
}

export interface CreatorsListState {
  /** Every loaded row in server order, de-duplicated by canonical creator key. */
  items: CreatorListItem[]
  /** Total creators matching the current search/order before pagination. */
  total: number
  /** Metadata coverage reported by the backend for this selection. */
  coverage: CreatorListResponse['coverage'] | null
  isPending: boolean
  isFetchingMore: boolean
  isError: boolean
  error: unknown
  hasMore: boolean
  loadMore: () => Promise<void>
  refetch: () => void
}

/**
 * Bounded, incremental personal creator browse loader (issue #2774).
 *
 * The first visit requests exactly one bounded page from the #2775 discovery
 * contract. Later pages append through `loadMore`, so already rendered rows
 * stay on screen, the selection/order stays stable, and a canonical creator can
 * never render twice when the server repeats a row across a page boundary.
 */
export function useCreatorsList(
  selection: CreatorListSelection,
  listApi: CreatorsListApi = creatorsApi,
): CreatorsListState {
  const query = useInfiniteQuery({
    ...creatorListQueryOptions(selection, listApi),
    retry: false,
  })

  const pages = query.data?.pages ?? []
  const firstPage = pages[0] ?? null

  const seen = new Set<string>()
  const items = pages.flatMap((page) =>
    page.items.filter((item) => {
      if (seen.has(item.canonical_creator_key)) return false
      seen.add(item.canonical_creator_key)
      return true
    }),
  )

  const loadMore = useCallback((): Promise<void> => {
    if (!query.hasNextPage || query.isFetchingNextPage) {
      return Promise.resolve()
    }
    return query.fetchNextPage().then(() => undefined)
  }, [query])

  return {
    items,
    total: firstPage?.total ?? 0,
    coverage: firstPage?.coverage ?? null,
    isPending: query.isPending,
    isFetchingMore: query.isFetchingNextPage,
    isError: query.isError,
    error: query.error,
    hasMore: query.hasNextPage ?? false,
    loadMore,
    refetch: () => {
      void query.refetch()
    },
  }
}
