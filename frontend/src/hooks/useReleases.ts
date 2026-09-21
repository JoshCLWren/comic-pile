import { useCallback } from 'react'
import { useInfiniteQuery } from '@tanstack/react-query'
import { releasesApi, type Release, type ReleaseListResponse } from '../services/api-releases'
import { queryKeys } from '../query/queryKeys'

export const RELEASES_PAGE_SIZE = 20

type ReleasesListApi = Pick<typeof releasesApi, 'list'>

function normalizeReleasesError(error: unknown): Error | null {
  if (error == null) return null
  if (error instanceof Error) return error
  return new Error('Release notes could not be loaded.')
}

/**
 * Canonical bounded Releases list query options: the documented
 * `releases.pages` key plus the exact first-page fetch contract consumed by
 * `useReleases`.
 *
 * The backend serves `limit`/`offset` pages with an authoritative `total`;
 * the offset lives in `pageParam`, never in the key, so every page of one
 * page size shares the stable `queryKeys.releases.list(...)` prefix.
 *
 * @param limit - Page size for every offset page.
 * @param listApi - Injectable release-list loader (defaults to the real service).
 */
export function releasesQueryOptions(
  limit: number = RELEASES_PAGE_SIZE,
  listApi: ReleasesListApi = releasesApi,
) {
  return {
    queryKey: queryKeys.releases.list({ pageSize: limit }),
    queryFn: ({ pageParam }: { pageParam: number }) => listApi.list(limit, pageParam),
    initialPageParam: 0,
    getNextPageParam: (lastPage: ReleaseListResponse, allPages: ReleaseListResponse[]) => {
      const loaded = allPages.reduce((sum, page) => sum + page.releases.length, 0)
      return loaded < lastPage.total ? loaded : undefined
    },
  }
}

export interface ReleasesState {
  releases: Release[]
  total: number
  isPending: boolean
  isFetchingMore: boolean
  isError: boolean
  error: Error | null
  hasMore: boolean
  loadMore: () => Promise<void>
  retry: () => Promise<void>
  refetch: () => void
}

/**
 * Bounded, incremental Releases loader built on TanStack Query's infinite
 * query and the canonical `releases.pages` query key.
 *
 * The first render requests exactly one bounded page. Later pages append
 * through `loadMore` (driven by the backend `total`), never by automatic
 * traversal. A failed next page retries the exact failed offset through
 * `retry`; a failed first page retries through `refetch` inside the same
 * `retry` entry point.
 *
 * @param limit - Page size for every offset page.
 * @param listApi - Injectable release-list loader (defaults to the real service).
 */
export function useReleases(
  limit: number = RELEASES_PAGE_SIZE,
  listApi: ReleasesListApi = releasesApi,
): ReleasesState {
  const query = useInfiniteQuery({
    ...releasesQueryOptions(limit, listApi),
    retry: false,
  })

  const pages = query.data?.pages ?? []
  const releases = pages.flatMap(page => page.releases)
  const total = pages[0]?.total ?? 0

  const loadMore = useCallback((): Promise<void> => {
    if (!query.hasNextPage || query.isFetchingNextPage) {
      return Promise.resolve()
    }
    return query.fetchNextPage().then(() => undefined)
  }, [query])

  const retry = useCallback((): Promise<void> => {
    if (pages.length === 0) {
      return query.refetch().then(() => undefined)
    }
    return query.fetchNextPage().then(() => undefined)
  }, [query, pages.length])

  return {
    releases,
    total,
    isPending: query.isPending,
    isFetchingMore: query.isFetchingNextPage,
    isError: query.isError,
    error: normalizeReleasesError(query.error),
    hasMore: query.hasNextPage ?? releases.length < total,
    loadMore,
    retry,
    refetch: () => {
      void query.refetch()
    },
  }
}
