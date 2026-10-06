import { useMutation, useQuery } from '@tanstack/react-query'
import { queryClient } from '../query/queryClient'
import { queryKeys } from '../query/queryKeys'
import { invalidateComicVineIssueIntelligenceMany } from '../query/cacheEffects'
import { seriesMappingApi } from '../services/api-series-mapping'
import type { SeriesMappingCommitResponse } from '../services/api-series-mapping'

/**
 * Preview which sibling issues in a corrected issue's series can be mapped to the
 * same provider volume (issue #3159).
 *
 * The preview is enabled only once the anchor issue carries a confirmed provider
 * volume, because sibling scope is licensed by that confirmation rather than by
 * thread membership alone.
 *
 * @param originIssueId - The corrected ComicPile issue that anchors the offer.
 * @param provider - External provider name, for example `comicvine`.
 * @param providerSeriesExternalId - The confirmed provider volume identifier.
 * @param enabled - Whether the offer should request a preview at all.
 * @returns TanStack Query result for the read-only sibling mapping preview.
 */
export function useSiblingSeriesMappingPreview(
  originIssueId: number | null,
  provider: string | null,
  providerSeriesExternalId: string | null,
  enabled = true,
) {
  const scopeLicensed = !!originIssueId && !!provider && !!providerSeriesExternalId

  return useQuery({
    queryKey:
      scopeLicensed
        ? queryKeys.comicVine.seriesMappingPreview(
            originIssueId!,
            provider!,
            providerSeriesExternalId!,
          )
        : [],
    queryFn: () =>
      seriesMappingApi.preview({
        origin_issue_id: originIssueId!,
        provider: provider!,
        provider_series_external_id: providerSeriesExternalId!,
      }),
    enabled: enabled && scopeLicensed,
  })
}

/**
 * Commit the sibling rows the reader approved on the preview surface.
 *
 * The preview token is user-bound, single-use in effect, and expires, so a stale
 * or expired preview is re-read rather than retried blindly.
 */
export function useCommitSeriesMapping() {
  return useMutation<SeriesMappingCommitResponse, unknown, Parameters<typeof seriesMappingApi.commit>[0]>({
    mutationFn: (request) => seriesMappingApi.commit(request),
    onSuccess: async (result) => {
      await invalidateComicVineIssueIntelligenceMany(queryClient, result.confirmed_issue_ids)
    },
  })
}