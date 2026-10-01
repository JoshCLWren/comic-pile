import { useCallback, useMemo } from 'react'
import { useCrossoverGroups, type CrossoverGroupsApi } from '../../hooks/useCrossoverGroups'
import { dependencyGroupsApi } from '../../services/api-dependency-groups'
import type { DependencyGroupSummary } from '../../services/api-dependency-groups'
import type { ThreadListItem } from '../../types'

export interface QueueCrossovers {
  /** Crossover memberships the page resolved for one queue thread. */
  groupsForThread: (threadId: number) => DependencyGroupSummary[]
  /** True while the batched crossover request for the queue is in flight. */
  isPending: boolean
  /** True when the batched crossover request failed. */
  hasError: boolean
}

const NO_GROUPS: DependencyGroupSummary[] = []

/**
 * Resolve crossover memberships for the whole queue with one batched request.
 *
 * QueueThreadCard is presentational, so the queue view owns crossover loading
 * here instead of letting every rendered row fetch its own slice. A
 * self-fetching card turns one queue load into N function invocations and N
 * requests (issue #2979); this hook keeps it at one request per 200 threads.
 *
 * @param threads - The active queue threads the list renders.
 * @param api - Injectable crossover client (defaults to the real service) so
 *   tests can substitute a faithful in-memory implementation.
 * @returns A per-thread accessor plus the shared loading/error state.
 */
export function useQueueCrossovers(
  threads: ThreadListItem[],
  api: CrossoverGroupsApi = dependencyGroupsApi,
): QueueCrossovers {
  const threadIds = useMemo(() => threads.map((thread) => thread.id), [threads])
  const { groupsByThreadId, isPending, error } = useCrossoverGroups(threadIds, api)

  const groupsForThread = useCallback(
    (threadId: number) => groupsByThreadId[threadId] ?? NO_GROUPS,
    [groupsByThreadId],
  )

  return useMemo(
    () => ({ groupsForThread, isPending, hasError: Boolean(error) }),
    [groupsForThread, isPending, error],
  )
}