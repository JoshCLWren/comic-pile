import { keepPreviousData, useInfiniteQuery } from '@tanstack/react-query'
import { queryKeys } from '../query/queryKeys'
import { comicVineApi } from '../services/api-comicvine'
import type { ComicVineSeriesSearchResponse } from '../services/api-comicvine'

interface UseComicVineSearchOptions {
  query: string
  pageSize?: number
  enabled?: boolean
}

const DEFAULT_PAGE_SIZE = 20

export function useComicVineSearch({
  query,
  pageSize = DEFAULT_PAGE_SIZE,
  enabled = true,
}: UseComicVineSearchOptions) {
  return useInfiniteQuery({
    queryKey: queryKeys.comicvine.search(query, pageSize),
    queryFn: async ({ pageParam = 0 }: { pageParam?: number }) => {
      const response: ComicVineSeriesSearchResponse = await comicVineApi.searchSeries(
        query,
        pageSize,
        pageParam || 0
      )
      return response
    },
    enabled: enabled && !!query.trim(),
    // Keep the reader's current results visible while a new query settles so the
    // list and its load-more control do not flash empty on every keystroke.
    placeholderData: keepPreviousData,
    staleTime: 5 * 60 * 1000, // 5 minutes
    getNextPageParam: (lastPage: ComicVineSeriesSearchResponse) => lastPage.next_offset,
    initialPageParam: 0,
  })
}