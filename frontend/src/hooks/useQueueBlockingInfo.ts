import { useQuery } from '@tanstack/react-query'
import { queryKeys } from '../query/queryKeys'
import { dependenciesApi } from '../services/api'
import type { BlockingDependency } from '../types'

const EMPTY_BLOCKING_MAP: Record<number, BlockingDependency[]> = {}

function toBlockingMap(response: Awaited<ReturnType<typeof dependenciesApi.getBatchBlockingInfo>>) {
  const map: Record<number, BlockingDependency[]> = {}
  for (const [threadId, info] of Object.entries(response.threads)) {
    map[Number(threadId)] = info.blocking_dependencies ?? []
  }
  return map
}

/**
 * Loads blocking dependency details for the supplied queue threads with one
 * batched request, never one request per card.
 *
 * Queue cards only need blocker names when they render their locked state, so
 * an in-flight, empty, or failed load degrades to the plain
 * "Blocked by dependency" tooltip instead of blocking rendering.
 */
export function useQueueBlockingInfo(
  threadIds: number[],
): Record<number, BlockingDependency[]> {
  const sortedIds = [...threadIds].sort((a, b) => a - b)

  const query = useQuery({
    queryKey: queryKeys.dependencies.blockingBatch(sortedIds),
    queryFn: () => dependenciesApi.getBatchBlockingInfo(sortedIds).then(toBlockingMap),
    enabled: sortedIds.length > 0,
    staleTime: 30_000,
    retry: false,
  })

  return query.data ?? EMPTY_BLOCKING_MAP
}
