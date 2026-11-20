import { useCallback, useMemo } from 'react'
import type { RollBootstrapResponse } from '../../types/rollBootstrap'
import { queryClient } from '../../query/queryClient'

/**
 * Sessionless Roll state the Queue reads: the pending roll and the snoozed
 * series, both derived from the Roll bootstrap (event-derived state).
 */
export interface QueueRollState {
  pending_thread_id: number | null
  /** Complete set of snoozed series ids (not the 20-row display summary). */
  snoozed_thread_ids: number[]
}

interface UseRollPendingSyncParams {
  rollBootstrap: RollBootstrapResponse | null | undefined
  refetchQueue: () => Promise<void>
}

interface UseRollPendingSyncResult {
  rollState: QueueRollState | undefined
  onUpdated: () => Promise<void>
  onRefetchRollState: () => Promise<void>
}

export function useRollPendingSync({
  rollBootstrap,
  refetchQueue,
}: UseRollPendingSyncParams): UseRollPendingSyncResult {
  // Bootstrap is authoritative, including when pending_thread_id is null.
  const rollState = useMemo<QueueRollState | undefined>(() => {
    if (rollBootstrap == null) return undefined
    // `snoozed_threads` is capped at 20 display rows; the id list is complete.
    // The summary ids are merged for payloads that predate the id list.
    const snoozedIds = new Set<number>(rollBootstrap.snoozed_thread_ids ?? [])
    for (const thread of rollBootstrap.snoozed_threads ?? []) snoozedIds.add(thread.id)
    return {
      pending_thread_id: rollBootstrap.pending_thread_id,
      snoozed_thread_ids: Array.from(snoozedIds),
    }
  }, [rollBootstrap])

  const onUpdated = useCallback(async () => {
    await refetchQueue()
    if (rollBootstrap) {
      await queryClient.refetchQueries({ queryKey: ['roll', 'bootstrap'] })
    }
  }, [refetchQueue, rollBootstrap])

  const onRefetchRollState = useCallback(async () => {
    await queryClient.refetchQueries({ queryKey: ['roll', 'bootstrap'] })
  }, [])

  return { rollState, onUpdated, onRefetchRollState }
}
