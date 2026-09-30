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
  crossoverGroupsByThreadId: Record<number, DependencyGroupSummary[]>
  crossoverGroupsPending: boolean
  crossoverGroupsError: boolean
  getCrossoverGroupsForThread: (thread: ThreadListItem) => DependencyGroupSummary[]
}

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
    crossoverGroupsByThreadId,
    crossoverGroupsPending,
    crossoverGroupsError,
    getCrossoverGroupsForThread,
  }
}