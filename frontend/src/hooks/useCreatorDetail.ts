import { useCallback } from 'react'
import { useInfiniteCollection } from '../pagination/useInfiniteCollection'
import { creatorsApi } from '../services/api-creators'
import type { CreatorDetailResponse, CreatorInsights, CreatorIssueRow, CreatorSeriesGroup } from '../services/api-creators'
import { queryKeys } from '../query/queryKeys'

export const CREATOR_DETAIL_PAGE_SIZE = 50

type CreatorsDetailApi = Pick<typeof creatorsApi, 'getDetail'>

/**
 * Canonical bounded creator detail query options: the documented
 * `creator.detail` key plus the exact first-page fetch contract consumed by
 * `useCreatorDetail`.
 *
 * The backend serves a shared `limit`/`offset` page across all three
 * collections with a string `next_cursor`; the cursor lives in `pageParam`,
 * never in the key.
 */
export function creatorDetailQueryOptions(
  creatorKey: string | null | undefined,
  limit: number = CREATOR_DETAIL_PAGE_SIZE,
  detailApi: CreatorsDetailApi = creatorsApi,
) {
  return {
    queryKey: creatorKey ? queryKeys.creator.detail(creatorKey, { limit }) : [],
    queryFn: ({ pageParam }: { pageParam: number }) =>
      detailApi.getDetail(creatorKey!, pageParam > 0 ? { limit, offset: pageParam } : { limit }),
    initialPageParam: 0,
    getNextPageParam: (lastPage: CreatorDetailResponse) =>
      lastPage.next_cursor != null && /^\d+$/.test(lastPage.next_cursor)
        ? Number(lastPage.next_cursor)
        : undefined,
  }
}

export interface CreatorDetailState {
  summary: CreatorDetailResponse['summary'] | null
  coverage: CreatorDetailResponse['coverage'] | null
  roleStats: CreatorDetailResponse['role_stats']
  ratingDistribution: CreatorDetailResponse['rating_distribution']
  insights: CreatorInsights | null
  seriesGroups: CreatorSeriesGroup[]
  seriesGroupsTotal: number
  seriesGroupsComplete: boolean
  ratedIssues: CreatorIssueRow[]
  headlineRoles: string[]
  readUnratedIssues: CreatorIssueRow[]
  upcomingIssues: CreatorIssueRow[]
  isPending: boolean
  isFetchingMore: boolean
  isError: boolean
  error: unknown
  hasMore: boolean
  loadMore: () => Promise<void>
  refetch: () => void
}

/**
 * Bounded, incremental creator detail loader (issue #2030).
 *
 * The first navigation requests exactly one bounded page. Later pages append
 * through `loadMore` (driven by the backend `next_cursor`) so already
 * rendered rows stay on screen while the next page loads. Summary, coverage,
 * and role stats always come from the first page.
 */
export function useCreatorDetail(
  creatorKey: string | null | undefined,
  limit: number = CREATOR_DETAIL_PAGE_SIZE,
  detailApi: CreatorsDetailApi = creatorsApi,
): CreatorDetailState {
  const query = useInfiniteCollection<CreatorIssueRow, CreatorDetailResponse, number>({
    ...creatorDetailQueryOptions(creatorKey, limit, detailApi),
    // The detail response carries three independent collections; the flat
    // `items` view is the rated-issue projection, while the component reads
    // the other collections from the shared page cache below.
    selectPage: (page) => page.rated_issues,
    enabled: !!creatorKey,
    retry: false,
    staleTime: 5 * 60 * 1000, // 5 minutes
    gcTime: 10 * 60 * 1000, // 10 minutes
  })

  const pages = query.pages
  const firstPage = pages[0] ?? null

  const ratedIssues = pages.flatMap((page) => page.rated_issues)
  const readUnratedIssues = pages.flatMap((page) => page.read_unrated_issues)
  const upcomingIssues = pages.flatMap((page) => page.upcoming_issues)

  const loadMore = useCallback((): Promise<void> => {
    if (!query.hasNextPage || query.isNextPageLoading) {
      return Promise.resolve()
    }
    return query.fetchNextPage()
  }, [query])

  return {
    summary: firstPage?.summary ?? null,
    coverage: firstPage?.coverage ?? null,
    roleStats: firstPage?.role_stats ?? [],
    ratingDistribution: firstPage?.rating_distribution ?? null,
    insights: firstPage?.insights ?? null,
    seriesGroups: firstPage?.series_groups ?? [],
    seriesGroupsTotal: firstPage?.series_groups_total ?? 0,
    seriesGroupsComplete: firstPage?.series_groups_complete ?? true,
    ratedIssues,
    headlineRoles: firstPage?.headline_roles ?? [],
    readUnratedIssues,
    upcomingIssues,
    isPending: query.isInitialLoading,
    isFetchingMore: query.isNextPageLoading,
    isError: query.isError,
    error: query.error,
    hasMore: query.hasNextPage,
    loadMore,
    refetch: () => {
      void query.refetch()
    },
  }
}
