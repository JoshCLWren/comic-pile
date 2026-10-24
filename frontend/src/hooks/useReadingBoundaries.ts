import { useQuery } from '@tanstack/react-query'
import { readingBoundariesApi } from '../services/api-reading-boundaries'
import { queryKeys } from '../query/queryKeys'

/** Reading state shares dependency invalidation after reads, list edits and rule changes. */
export function useReadingBoundaries(threadIds: number[], enabled = true) {
  const ids = [...new Set(threadIds.filter((id) => Number.isSafeInteger(id) && id > 0))].sort((a, b) => a - b)
  return useQuery({
    queryKey: queryKeys.dependencies.readingBoundaries(ids),
    queryFn: () => readingBoundariesApi.batch(ids),
    enabled: enabled && ids.length > 0,
  })
}
