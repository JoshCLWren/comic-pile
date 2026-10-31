import { useQuery } from '@tanstack/react-query'
import type { components } from '../generated/openapi'
import { threadsApi } from '../services/api-threads'
import { queryKeys } from '../query/queryKeys'

type ComicVineMappingHealth = components['schemas']['ComicVineMappingHealth']

/**
 * Read the stored ComicVine mapping health for one owned thread.
 *
 * The query is only enabled while the Roll action sheet is open, so Roll view
 * load never pays a per-row request. A failed fetch is never treated as a
 * mapping candidate: the backend is unavailable and Roll stays usable.
 */
export function useRollMappingHealth(threadId: number | null, enabled: boolean) {
  return useQuery({
    queryKey: threadId ? queryKeys.comicVine.mappingHealth(threadId) : [],
    queryFn: () => threadsApi.comicvineMappingHealth(threadId!),
    enabled: enabled && threadId !== null,
  })
}

/**
 * Decide whether an idle Roll row may offer the Map series action.
 *
 * Only statuses that actually have unmapped or review-needed issues qualify.
 * `fully_mapped` and `not_applicable` are excluded, and a missing/failed
 * health read fails closed.
 */
export function isRollMapSeriesCandidate(
  health: ComicVineMappingHealth | null | undefined,
): boolean {
  if (!health) return false
  return (
    health.status === 'unresolved' ||
    health.status === 'needs_review' ||
    health.status === 'partial'
  )
}

export type { ComicVineMappingHealth }
