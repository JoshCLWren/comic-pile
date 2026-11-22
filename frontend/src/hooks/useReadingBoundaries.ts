import { useQuery, useQueryClient } from '@tanstack/react-query'
import { readingBoundariesApi } from '../services/api-reading-boundaries'
import { recordReadingBoundaryEvaluator } from '../query/cacheEffects'
import { queryKeys } from '../query/queryKeys'

/** Reading state shares dependency invalidation after reads, list edits and rule changes. */
export function useReadingBoundaries(threadIds: number[], enabled = true) {
  const client = useQueryClient()
  const ids = [...new Set(threadIds.filter((id) => Number.isSafeInteger(id) && id > 0))].sort((a, b) => a - b)
  return useQuery({
    queryKey: queryKeys.dependencies.readingBoundaries(ids),
    queryFn: async () => {
      const evaluator = client.getQueryData<'enabled' | 'unavailable'>(
        queryKeys.dependencies.readingBoundaryEvaluator(),
      )
      // Once any batch identifies the deployment-wide evaluator as unavailable,
      // another canonical request cannot add information. The empty projection
      // drives the same legacy fallback as the server's per-thread unavailable
      // rows, while avoiding that repeated batch on other views and refetches.
      if (evaluator === 'unavailable') {
        return { threads: {}, evaluator }
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
