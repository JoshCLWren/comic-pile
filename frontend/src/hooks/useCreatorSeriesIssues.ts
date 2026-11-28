import { useCallback } from 'react'
import { useInfiniteQuery, type InfiniteData, type FetchStatus } from '@tanstack/react-query'
import { creatorsApi } from '../services/api-creators'
import type { CreatorIssueRow, CreatorSeriesIssueListResponse } from '../services/api-creators'
import { queryKeys } from '../query/queryKeys'

type CreatorSeriesIssuesApi = Pick<typeof creatorsApi, 'getSeriesIssues'>

export const CREATOR_SERIES_ISSUES_PAGE_SIZE = 50

export interface CreatorSeriesIssuesState {
  data: InfiniteData<CreatorSeriesIssueListResponse> | undefined
  fetchStatus: FetchStatus
  issues: CreatorIssueRow[]
  total: number
  isPending: boolean
  isFetchingMore: boolean
  isError: boolean
  error: unknown
  hasMore: boolean
  loadMore: () => Promise<void>
  refetch: () => void
}

/**
 * Paginated drill-down of the exact issues backing one creator series group
 * (issue #3579).
 *
 * Pages are cached under `['creators', 'seriesIssues', creatorKey, seriesKey]`,
 * so a creator's rows can never bleed into another creator's cached panel for
 * the same series. Pagination lives in TanStack React Query (not hand-written
 * `useState`/`useEffect` fetching), so a pending response for creator A can
 * never append rows to creator B's list.
 *
 * The query is enabled only while the caller asks for it, so a creator page
 * fetches drill-down rows only after the reader expands a series group. The
 * response echoes the same canonical series key and all-credits population
 * scope as the parent group, so the rendered evidence cannot drift from the
 * aggregate.
 */
export function useCreatorSeriesIssues(
  creatorKey: string | null | undefined,
  seriesKey: string | null | undefined,
  {
    enabled = true,
    seriesIssuesApi = creatorsApi,
  }: { enabled?: boolean; seriesIssuesApi?: CreatorSeriesIssuesApi } = {},
): CreatorSeriesIssuesState {
  const query = useInfiniteQuery({
    queryKey: queryKeys.creators.seriesIssues(creatorKey ?? '', seriesKey ?? ''),
    queryFn: ({ pageParam }: { pageParam: number }) => {
      const offset = pageParam
      return seriesIssuesApi.getSeriesIssues(creatorKey!, seriesKey!, { offset })
    },
    initialPageParam: 0,
    getNextPageParam: (lastPage: CreatorSeriesIssueListResponse) =>
      lastPage.next_cursor != null && /^\d+$/.test(lastPage.next_cursor)
        ? Number(lastPage.next_cursor)
        : undefined,
    enabled: enabled && !!creatorKey && !!seriesKey,
    retry: false,
  })

  const pages = query.data?.pages ?? []
  const firstPage = pages[0] ?? null
  const issues = pages.flatMap((page) => page.issues)

  const loadMore = useCallback((): Promise<void> => {
    if (!query.hasNextPage || query.isFetchingNextPage) {
      return Promise.resolve()
    }
    return query.fetchNextPage().then(() => undefined)
  }, [query])

  // isError should only be true for the initial request, not for subsequent page failures
  const isInitialError = query.isError && pages.length === 0

  return {
    data: query.data,
    fetchStatus: query.fetchStatus,
    issues,
    total: firstPage?.total ?? 0,
    isPending: query.isPending,
    isFetchingMore: query.isFetchingNextPage,
    isError: isInitialError,
    error: query.error,
    hasMore: query.hasNextPage ?? false,
    loadMore,
    refetch: () => {
      void query.refetch()
    },
  }
}
