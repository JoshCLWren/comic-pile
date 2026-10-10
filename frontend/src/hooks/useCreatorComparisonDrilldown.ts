import { useInfiniteQuery } from '@tanstack/react-query'
import {
  creatorComparisonApi,
  DRILLDOWN_PAGE_SIZE,
  type CreatorComparisonApi,
} from '../services/creatorComparisonApi'
import { queryKeys } from '../query/queryKeys'
import type {
  CreatorDrilldownData,
  CreatorDrilldownIssue,
  CreatorDrilldownRatingObservation,
} from '../types/index'

/** Server-side creator-comparison drilldown metrics (issue #3176). */
export type CreatorDrilldownMetric =
  | 'average'
  | 'median'
  | 'distribution'
  | '5-star-rate'
  | 'role-average'
  | 'series-average'
  | 'read-without-rating'
  | 'unread'

/** One drilled metric selection: canonical creator key plus metric scoping. */
export interface CreatorDrilldownSelection {
  creatorKey: string
  metric: CreatorDrilldownMetric
  bucket?: string
  role?: string
  series?: string
}

export interface CreatorDrilldownState {
  /** First evidence page carrying the canonical calculation and total count. */
  data: CreatorDrilldownData | null
  /** Issue evidence rows accumulated across every loaded page, in server order. */
  issues: CreatorDrilldownIssue[]
  /** Ranked rating observations accumulated across pages (median metric only). */
  observations: CreatorDrilldownRatingObservation[]
  isPending: boolean
  isFetchingMore: boolean
  isError: boolean
  error: unknown
  hasMore: boolean
  loadMore: () => Promise<void>
}

/**
 * Bounded creator-comparison metric drilldown loader (issue #3176).
 *
 * The first page carries the human-readable calculation and the total
 * evidence-set size; later pages append through `loadMore` using the
 * backend's opaque offset cursor, so large creators stay bounded and
 * responsive. Summary and evidence share the backend's aggregation
 * semantics, so the visible metric and the evidence page always reconcile.
 *
 * @param selection - The drilled metric selection, or `null` when closed.
 * @param api - The creator comparison API used for requests.
 * @returns The drilldown state for the current selection.
 */
export function useCreatorComparisonDrilldown(
  selection: CreatorDrilldownSelection | null,
  api: CreatorComparisonApi = creatorComparisonApi,
): CreatorDrilldownState {
  const enabled = selection != null && selection.creatorKey.trim() !== ''

  const query = useInfiniteQuery({
    queryKey: enabled
      ? queryKeys.creators.drilldown({
          creatorKey: selection.creatorKey,
          metric: selection.metric,
          bucket: selection.bucket,
          role: selection.role,
          series: selection.series,
          limit: DRILLDOWN_PAGE_SIZE,
        })
      : ['creators', 'drilldown', 'closed'],
    queryFn: ({ pageParam }: { pageParam?: string | null }) => {
      if (!selection) throw new Error('No drilldown selection')
      // SAFETY: useInfiniteQuery starts at the null initialPageParam and only
      // advances with page tokens, so the first page is always a null cursor.
      const params = {
        creator: selection.creatorKey,
        limit: DRILLDOWN_PAGE_SIZE,
        cursor: pageParam ?? null,
      }
      switch (selection.metric) {
        case 'average':
          return api.getAverageDrilldown(params)
        case 'median':
          return api.getMedianDrilldown(params)
        case 'distribution':
          if (!selection.bucket) throw new Error('Bucket is required for distribution drilldown')
          return api.getDistributionDrilldown({ ...params, bucket: selection.bucket })
        case '5-star-rate':
          return api.getFiveStarRateDrilldown(params)
        case 'role-average':
          if (!selection.role) throw new Error('Role is required for role-average drilldown')
          return api.getRoleAverageDrilldown({ ...params, role: selection.role })
        case 'series-average':
          if (!selection.series) throw new Error('Series is required for series-average drilldown')
          return api.getSeriesAverageDrilldown({ ...params, series: selection.series })
        case 'read-without-rating':
          return api.getReadWithoutRatingDrilldown(params)
        case 'unread':
          return api.getUnreadDrilldown(params)
      }
    },
    // SAFETY: null is the intentional first pageParam; useInfiniteQuery types it
    // as string after the first page, so the null literal is asserted here.
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage: CreatorDrilldownData) => lastPage.next_cursor,
    enabled,
    retry: false,
  })

  const pages = query.data?.pages ?? []
  const firstPage = pages[0] ?? null

  return {
    data: firstPage,
    issues: pages.flatMap((page) => ('issues' in page ? page.issues : [])),
    observations: pages.flatMap((page) =>
      'sorted_ratings' in page ? page.sorted_ratings : [],
    ),
    isPending: query.isPending,
    isFetchingMore: query.isFetchingNextPage,
    isError: query.isError,
    error: query.error,
    hasMore: query.hasNextPage ?? false,
    loadMore: () => {
      if (!query.hasNextPage || query.isFetchingNextPage) {
        return Promise.resolve()
      }
      return query.fetchNextPage().then(() => undefined)
    },
  }
}
