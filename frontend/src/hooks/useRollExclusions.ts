import { useCallback } from 'react'
import { useInfiniteCollection } from '../pagination'
import { queryKeys } from '../query/queryKeys'
import { rollExclusionsApi } from '../services/rollExclusionsApi'
import type {
  RollExclusionCategory,
  RollExclusionPageResponse,
  ThreadExclusionReason,
} from '../types/rollBootstrap'

/**
 * Page size for the Roll exclusion drill-down. It matches the bootstrap
 * preview limit so expanding a section replaces the preview with the same
 * first page instead of re-showing a different slice (issue #3330).
 */
export const ROLL_EXCLUSION_PAGE_SIZE = 20

/** API surface the Roll exclusion drill-down depends on. */
export type RollExclusionsApi = Pick<typeof rollExclusionsApi, 'list'>

/**
 * Options for the Roll exclusion drill-down.
 */
export interface UseRollExclusionsOptions {
  /** Only fetch while the section is actually expanded. */
  enabled?: boolean
  /** Injectable API subset; defaults to the real service. */
  api?: RollExclusionsApi
}

/**
 * Incrementally loads every blocked or out-of-pool series for one category.
 *
 * The Roll bootstrap keeps its bounded preview, so the collapsed section
 * heading reads the authoritative category total from the bootstrap response
 * while the expanded section pages through rows on demand. `total` below comes
 * from the same server predicate the bootstrap count uses, so the heading and
 * the loaded list can never tell different stories.
 *
 * @param category - `blocked` or `inactive`.
 * @param options - Lazy-load gate and injectable API.
 * @returns Canonical pagination state, the authoritative category total, and a
 *   `retry` that resumes the page that actually failed.
 */
export function useRollExclusions(
  category: RollExclusionCategory,
  { enabled = true, api = rollExclusionsApi }: UseRollExclusionsOptions = {},
) {
  const query = useInfiniteCollection<
    ThreadExclusionReason,
    RollExclusionPageResponse,
    string | null
  >({
    queryKey: queryKeys.roll.exclusions(category),
    queryFn: ({ pageParam }) =>
      api.list(category, {
        limit: ROLL_EXCLUSION_PAGE_SIZE,
        offset: Number(pageParam ?? 0),
      }),
    initialPageParam: null,
    getNextPageParam: (page) => page.next_cursor,
    selectPage: (page) => page.items,
    enabled,
    retry: false,
  })

  const total = query.pages[0]?.total ?? 0

  /**
   * Retry a failed load of this category.
   *
   * A failed first page has nothing to resume from, so the retry refetches the
   * collection from its first page. A failed next page keeps the rows the
   * reader already has, so the retry asks for the missing page instead of
   * reloading every page they already read (issue #3330).
   */
  const retry = useCallback(async (): Promise<void> => {
    if (query.pages.length > 0) {
      await query.fetchNextPage()
      return
    }
    await query.refetch()
  }, [query])

  return { ...query, total, retry }
}
