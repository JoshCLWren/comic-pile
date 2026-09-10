import { useQuery } from '@tanstack/react-query'
import { queryKeys } from '../query/queryKeys'
import { dependenciesApi } from '../services/api'
import type { BatchBlockingInfoResponse, BlockingDependency } from '../types'

const EMPTY_BLOCKING_MAP: Record<number, BlockingDependency[]> = {}

/** Batch blocking-info client seam. Production defaults to `dependenciesApi`. */
export interface QueueBlockingInfoApi {
  getBatchBlockingInfo: (threadIds: number[]) => Promise<BatchBlockingInfoResponse>
}

function toBlockingMap(response: BatchBlockingInfoResponse) {
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
 *
 * @param threadIds - Queue threads whose blocker names should be batched.
 * @param api - Injectable batch blocking-info client (defaults to the real
 *   service) so tests can substitute a faithful in-memory implementation.
 */
export function useQueueBlockingInfo(
  threadIds: number[],
  api: QueueBlockingInfoApi = dependenciesApi,
): Record<number, BlockingDependency[]> {
  const sortedIds = [...threadIds].sort((a, b) => a - b)

  const query = useQuery({
    queryKey: queryKeys.dependencies.blockingBatch(sortedIds),
    queryFn: () => api.getBatchBlockingInfo(sortedIds).then(toBlockingMap),
    enabled: sortedIds.length > 0,
    staleTime: 30_000,
    retry: false,
  })

  return query.data ?? EMPTY_BLOCKING_MAP
}
