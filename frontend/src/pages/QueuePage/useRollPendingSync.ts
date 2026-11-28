import { useCallback, useMemo } from 'react'
import type { RollState } from '../../types/rollState'
import { queryClient } from '../../query/queryClient'
import { queryKeys } from '../../query/queryKeys'

/**
 * Sessionless Roll state the Queue reads: the pending roll and the snoozed
 * series, both derived from the Roll bootstrap (event-derived state).
 */
export interface QueueRollState {
  pending_thread_id: number | null
  /** Complete set of snoozed series ids (not the 20-row display summary). */
  snoozed_thread_ids: number[]
}

/** Only the browser-owned fields the Queue actually needs. */
type QueueRollSource = Pick<
  RollState,
  'pending_thread_id' | 'snoozed_thread_ids' | 'snoozed_threads'
>

interface UseRollPendingSyncParams {
  rollState: QueueRollSource | null | undefined
  refetchQueue: () => Promise<void>
}

interface UseRollPendingSyncResult {
  rollState: QueueRollState | undefined
  onUpdated: () => Promise<void>
  onRefetchRollState: () => Promise<void>
}

export function useRollPendingSync({
  rollState,
  refetchQueue,
}: UseRollPendingSyncParams): UseRollPendingSyncResult {
  // Bootstrap is authoritative, including when pending_thread_id is null.
  const rollState = useMemo<QueueRollState | undefined>(() => {
    if (rollState == null) return undefined
    // `snoozed_threads` is capped at 20 display rows; the id list is complete.
    // The summary ids are merged for payloads that predate the id list.
    const snoozedIds = new Set<number>(rollState.snoozed_thread_ids ?? [])
    for (const thread of rollState.snoozed_threads ?? []) snoozedIds.add(thread.id)
    return {
      pending_thread_id: rollState.pending_thread_id,
      snoozed_thread_ids: Array.from(snoozedIds),
    }
  }, [rollState])

  const onUpdated = useCallback(async () => {
    await refetchQueue()
    if (rollState) {
      await queryClient.refetchQueries({ queryKey: queryKeys.roll.state() })
    }
  }, [refetchQueue, rollState])

  const onRefetchRollState = useCallback(async () => {
    await queryClient.refetchQueries({ queryKey: queryKeys.roll.state() })
  }, [])

  return { rollState, onUpdated, onRefetchRollState }
}
