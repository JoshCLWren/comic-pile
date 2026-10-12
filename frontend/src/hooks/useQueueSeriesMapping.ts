import { useMutation, useQuery } from '@tanstack/react-query'
import { issuesApi } from '../services/api-issues'
import { seriesMappingApi } from '../services/api-series-mapping'
import type { SeriesMappingCommitResponse } from '../services/api-series-mapping'
import { queryClient } from '../query/queryClient'
import { queryKeys } from '../query/queryKeys'
import {
  invalidateAfterQueueMutation,
  invalidateComicVineIssueIntelligenceMany,
} from '../query/cacheEffects'

/**
 * Resolve the issue that anchors a thread-level series-mapping preview (issue #2773).
 *
 * The series-mapping preview contract (#2721) anchors scope on one owned issue, so a
 * Queue row needs an origin before it can request a plan. The first unread issue is
 * the most likely repair target; when everything is read, the first issue anchors.
 * This query runs only while the Map series dialog is open, so Queue rendering never
 * pays for per-card issue fetches.
 *
 * @param threadId - The Queue thread being repaired.
 * @param enabled - Whether the repair dialog is open.
 * @returns The anchor issue, or null when the thread tracks no issues.
 */
export function useQueueMappingOriginIssue(threadId: number | null, enabled = true) {
  return useQuery({
    queryKey: threadId != null ? queryKeys.comicVine.queueSeriesOrigin(threadId) : [],
    queryFn: async () => {
      const page = await issuesApi.list(threadId!, { page_size: 100 })
      return page.issues.find((issue) => issue.status === 'unread') ?? page.issues[0] ?? null
    },
    enabled: enabled && threadId != null,
  })
}

/**
 * Read-only series-mapping preview for a thread-level repair (issues #2721/#2773).
 *
 * This is the same preview contract the sibling offer uses, anchored on the Queue
 * thread's origin issue instead of a freshly corrected one. Only rows the preview
 * classifies `safe_exact_match` may be bulk-approved; everything else is reported.
 *
 * @param originIssueId - The anchor issue from `useQueueMappingOriginIssue`.
 * @param provider - External provider name, for example `comicvine`.
 * @param providerSeriesExternalId - The selected provider volume identifier.
 * @param enabled - Whether a volume is selected and the preview step is visible.
 * @returns TanStack Query result for the read-only mapping preview.
 */
export function useQueueSeriesMappingPreview(
  originIssueId: number | null,
  provider: string | null,
  providerSeriesExternalId: string | null,
  enabled = true,
) {
  const scopeReady = !!originIssueId && !!provider && !!providerSeriesExternalId

  return useQuery({
    queryKey: scopeReady
      ? queryKeys.comicVine.seriesMappingPreview(originIssueId!, provider!, providerSeriesExternalId!)
      : [],
    queryFn: () =>
      seriesMappingApi.preview({
        origin_issue_id: originIssueId!,
        provider: provider!,
        provider_series_external_id: providerSeriesExternalId!,
      }),
    enabled: enabled && scopeReady,
  })
}

/**
 * Commit the thread-level rows the reader approved on the preview surface (#2722).
 *
 * On success the Queue pages reset through the canonical queue-mutation helper so
 * the mapping-health indicator refreshes without a hard reload, and the confirmed
 * issues' intelligence caches refresh alongside it. Callers must not refetch
 * manually after this helper.
 */
export function useQueueSeriesMappingCommit() {
  return useMutation<
    SeriesMappingCommitResponse,
    unknown,
    Parameters<typeof seriesMappingApi.commit>[0]
  >({
    mutationFn: (request) => seriesMappingApi.commit(request),
    onSuccess: async (result) => {
      await invalidateComicVineIssueIntelligenceMany(queryClient, result.confirmed_issue_ids)
      await invalidateAfterQueueMutation(queryClient)
    },
  })
}
