import { useCallback } from 'react'
import { useInfiniteQuery } from '@tanstack/react-query'
import { creatorsApi, type CreatorDetailResponse, type CreatorIssueRow } from '../services/api'
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
  ratedIssues: CreatorIssueRow[]
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
  const query = useInfiniteQuery({
    ...creatorDetailQueryOptions(creatorKey, limit, detailApi),
    enabled: !!creatorKey,
    retry: false,
  })

  const pages = query.data?.pages ?? []
  const firstPage = pages[0] ?? null

  const ratedIssues = pages.flatMap((page) => page.rated_issues)
  const readUnratedIssues = pages.flatMap((page) => page.read_unrated_issues)
  const upcomingIssues = pages.flatMap((page) => page.upcoming_issues)

  const loadMore = useCallback((): Promise<void> => {
    if (!query.hasNextPage || query.isFetchingNextPage) {
      return Promise.resolve()
    }
    return query.fetchNextPage().then(() => undefined)
  }, [query])

  return {
    summary: firstPage?.summary ?? null,
    coverage: firstPage?.coverage ?? null,
    roleStats: firstPage?.role_stats ?? [],
    ratedIssues,
    readUnratedIssues,
    upcomingIssues,
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
