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
 * @returns Canonical pagination state plus the authoritative category total.
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

  return { ...query, total }
}
