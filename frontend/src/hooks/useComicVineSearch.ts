import { keepPreviousData } from '@tanstack/react-query'
import { queryKeys } from '../query/queryKeys'
import { comicVineApi } from '../services/api-comicvine'
import type {
  ComicVineSeriesResult,
  ComicVineSeriesSearchResponse,
} from '../services/api-comicvine'
import { useInfiniteCollection } from '../pagination/useInfiniteCollection'

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
  return useInfiniteCollection<ComicVineSeriesResult, ComicVineSeriesSearchResponse, number>({
    queryKey: queryKeys.comicvine.search(query, pageSize),
    queryFn: ({ pageParam = 0 }) => comicVineApi.searchSeries(query, pageSize, pageParam || 0),
    enabled: enabled && !!query.trim(),
    // Keep the reader's current results visible while a new query settles so the
    // list and its load-more control do not flash empty on every keystroke.
    placeholderData: keepPreviousData,
    staleTime: 5 * 60 * 1000, // 5 minutes
    getNextPageParam: (lastPage) => lastPage.next_offset,
    selectPage: (page) => page.results,
    initialPageParam: 0,
  })
}