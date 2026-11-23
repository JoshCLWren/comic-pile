import { useQuery, useQueryClient } from '@tanstack/react-query'
import { readingBoundariesApi } from '../services/api-reading-boundaries'
import { recordReadingBoundaryEvaluator } from '../query/cacheEffects'
import { queryKeys } from '../query/queryKeys'

const EVALUATOR_CAPABILITY_TTL_MS = 30_000

/** Reading state shares dependency invalidation after reads, list edits and rule changes. */
export function useReadingBoundaries(threadIds: number[], enabled = true) {
  const client = useQueryClient()
  const ids = [...new Set(threadIds.filter((id) => Number.isSafeInteger(id) && id > 0))].sort((a, b) => a - b)
  return useQuery({
    queryKey: queryKeys.dependencies.readingBoundaries(ids),
    queryFn: async () => {
      const evaluatorState = client.getQueryState<'enabled' | 'unavailable'>(
        queryKeys.dependencies.readingBoundaryEvaluator(),
      )
      // Reuse a fresh unavailable discovery across route keys and refetches.
      // The empty projection drives the same legacy fallback as the server's
      // per-thread unavailable rows. Expire the shortcut with the normal query
      // freshness window so a later deployment can enable the evaluator without
      // requiring a reload or an auth transition.
      const discoveryIsFresh = evaluatorState != null &&
        Date.now() - evaluatorState.dataUpdatedAt < EVALUATOR_CAPABILITY_TTL_MS
      if (evaluatorState?.data === 'unavailable' && discoveryIsFresh) {
        return { threads: {}, evaluator: evaluatorState.data }
      }
      const response = await readingBoundariesApi.batch(ids)
      recordReadingBoundaryEvaluator(client, response.evaluator)
      return response
    },
    enabled: enabled && ids.length > 0,
    // Read state can change from another tab (a rating, an issue toggle, or a
    // completed run). Returning to an open page must not keep showing the
    // previous "available next" explanation (#4181 / MQA-QUEUE-010).
    refetchOnWindowFocus: 'always',
  })
}
