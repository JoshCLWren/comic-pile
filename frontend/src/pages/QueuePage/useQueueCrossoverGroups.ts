import { useCallback, useMemo } from 'react'
import { useCrossoverGroups } from '../../hooks/useCrossoverGroups'
import type { ThreadListItem } from '../../types'
import type { DependencyGroupSummary } from '../../services/api-dependency-groups'

/**
 * Stable empty membership so a queue card always receives a defined
 * `crossoverGroups` value (even while the page-level batch query is still
 * pending or has failed) and never falls back to its own per-card fetch.
 */
const EMPTY_CROSSOVER_GROUPS: DependencyGroupSummary[] = []

interface UseQueueCrossoverGroupsResult {
  crossoverGroupsPending: boolean
  crossoverGroupsError: boolean
  getCrossoverGroupsForThread: (thread: ThreadListItem) => DependencyGroupSummary[]
}

/**
 * Load crossover memberships for the whole visible queue with one batched
 * request instead of letting each `QueueThreadCard` request its own.
 *
 * Cards always receive a defined `crossoverGroups` value, so the card-level
 * `useCrossoverGroups([thread.id])` fallback stays disabled on the queue path
 * while the page-level batch is pending or has failed (issue #2979).
 *
 * @param activeThreads - Active queue threads rendered by `QueuePage`.
 * @returns The batch loading/error state plus a per-thread group lookup that
 *   returns a stable empty array for threads the response omitted.
 */
export function useQueueCrossoverGroups(
  activeThreads: ThreadListItem[],
): UseQueueCrossoverGroupsResult {
  const activeThreadIds = useMemo(
    () => activeThreads.map((thread) => thread.id),
    [activeThreads],
  )

  const {
    groupsByThreadId: crossoverGroupsByThreadId,
    isPending: crossoverGroupsPending,
    error: crossoverGroupsQueryError,
  } = useCrossoverGroups(activeThreadIds)
  const crossoverGroupsError = Boolean(crossoverGroupsQueryError)

  const getCrossoverGroupsForThread = useCallback(
    (thread: ThreadListItem) =>
      crossoverGroupsByThreadId[thread.id] ?? EMPTY_CROSSOVER_GROUPS,
    [crossoverGroupsByThreadId],
  )

  return {
    crossoverGroupsPending,
    crossoverGroupsError,
    getCrossoverGroupsForThread,
  }
}
