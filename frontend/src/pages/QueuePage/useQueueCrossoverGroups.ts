import { useCallback, useEffect, useMemo, useRef } from 'react'
import { useCrossoverGroups } from '../../hooks/useCrossoverGroups'
import type { ThreadListItem } from '../../types'
import type { DependencyGroupSummary } from '../../services/api-dependency-groups'

/**
 * Stable empty membership so a queue card always receives a defined
 * `crossoverGroups` value (even while the page-level batch query is still
 * pending or has failed) and never falls back to its own per-card fetch.
 */
const EMPTY_CROSSOVER_GROUPS: DependencyGroupSummary[] = []

/**
 * Stable "nothing resolved yet" map. Used as the initial last-resolved
 * snapshot so the identity check below can tell "no response has arrived" apart
 * from a resolved response that legitimately contains no memberships.
 */
const NO_GROUPS_BY_THREAD_ID: Record<number, DependencyGroupSummary[]> = {}

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
 * `useCrossoverGroups` keys its cache by the whole requested thread-id set, so
 * appending a queue page starts a brand-new pending query. The last resolved
 * snapshot is retained across that transition so already-rendered cards keep
 * their crossover badges instead of flashing the loading state again, matching
 * the per-card behavior this batching replaced.
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

  const hasResolvedBatch = Object.keys(crossoverGroupsByThreadId).length > 0
  const lastResolvedGroupsRef = useRef<Record<number, DependencyGroupSummary[]>>(
    NO_GROUPS_BY_THREAD_ID,
  )

  useEffect(() => {
    if (hasResolvedBatch) {
      lastResolvedGroupsRef.current = crossoverGroupsByThreadId
    }
  }, [crossoverGroupsByThreadId, hasResolvedBatch])

  const resolvedGroupsByThreadId = hasResolvedBatch
    ? crossoverGroupsByThreadId
    : lastResolvedGroupsRef.current
  const hasAnyResolvedData = resolvedGroupsByThreadId !== NO_GROUPS_BY_THREAD_ID

  const getCrossoverGroupsForThread = useCallback(
    (thread: ThreadListItem) => resolvedGroupsByThreadId[thread.id] ?? EMPTY_CROSSOVER_GROUPS,
    [resolvedGroupsByThreadId],
  )

  return {
    crossoverGroupsPending: crossoverGroupsPending && !hasAnyResolvedData,
    crossoverGroupsError: Boolean(crossoverGroupsQueryError) && !hasAnyResolvedData,
    getCrossoverGroupsForThread,
  }
}