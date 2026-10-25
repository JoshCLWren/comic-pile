import { useQuery } from '@tanstack/react-query'
import { creatorsApi } from '../services/api-creators'
import type { CreatorSeriesIssueListResponse } from '../services/api-creators'
import { queryKeys } from '../query/queryKeys'

type CreatorSeriesIssuesApi = Pick<typeof creatorsApi, 'getSeriesIssues'>

/**
 * Bounded drill-down of the exact issues backing one creator series group
 * (issue #3579).
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
) {
  return useQuery<CreatorSeriesIssueListResponse>({
    queryKey: queryKeys.creators.seriesIssues(creatorKey ?? '', seriesKey ?? ''),
    queryFn: () => seriesIssuesApi.getSeriesIssues(creatorKey!, seriesKey!),
    enabled: enabled && !!creatorKey && !!seriesKey,
    retry: false,
  })
}
