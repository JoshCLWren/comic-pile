import { useEffect, useState, useCallback } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { undoApi } from '../services/api-undo'
import { getApiErrorDetail } from '../utils/apiError'
import { queryKeys } from '../query/queryKeys'
import { queryClient } from '../query/queryClient'
import { invalidateAfterUndo } from '../query/cacheEffects'
import { useToast } from '../contexts/useToast'
import type { SessionSnapshotsResponse, UndoPayload } from '../types'

export function useSnapshots(sessionId: number | string | null | undefined) {
  const { data, isPending, isError, error } = useQuery({
    queryKey: sessionId != null ? queryKeys.undo.snapshots(sessionId) : [],
    queryFn: () => undoApi.listSnapshots(sessionId!),
    enabled: sessionId != null,
  })

  useEffect(() => {
    if (isError) {
      console.error('Failed to load snapshots:', getApiErrorDetail(error))
    }
  }, [isError, error])

  if (sessionId == null) {
    // SAFETY: no session id means no snapshots; null is the intentional shape when the query is disabled.
    return { data: null as SessionSnapshotsResponse | null, isPending: false, isError: false }
  }

  return { data: data ?? null, isPending, isError }
}

export function useUndo() {
  const { showToast } = useToast()

  const mutation = useMutation({
    mutationFn: ({ sessionId, snapshotId }: UndoPayload) => undoApi.undo(sessionId, snapshotId),
    // The undone rating rewrites thread, die, queue, and history state, so
    // every retained cache must refetch — otherwise Roll keeps rendering the
    // pre-undo state until a manual reload (#3194).
    onSuccess: async (_data, variables) => {
      await invalidateAfterUndo(queryClient, variables.sessionId)
    },
  })

  const mutate = useCallback(
    async ({ sessionId, snapshotId }: UndoPayload) => {
      try {
        await mutation.mutateAsync({ sessionId, snapshotId })
        showToast('Rating undone. Roll and History are up to date.', 'success')
      } catch (error: unknown) {
        console.error('Failed to undo action:', getApiErrorDetail(error))
        showToast('Undo failed. Nothing was changed.', 'error')
        throw error
      }
    },
    [mutation, showToast],
  )

  return { mutate, isPending: mutation.isPending, isError: mutation.isError }
}

/**
 * Undo the latest rating of a session without requiring the caller to know
 * the snapshot id. Powers the Undo action on the Roll page's "Just rated"
 * notice (#3194): after rating, the only undo affordance lived three clicks
 * deep in History, so the notice itself must offer the reversal.
 *
 * @returns The `undoLatest` action plus its pending state.
 */
export function useUndoLatestRating() {
  const { showToast } = useToast()
  const [isPending, setIsPending] = useState(false)

  const undoLatest = useCallback(
    async (sessionId: number | string): Promise<boolean> => {
      setIsPending(true)
      try {
        const snapshots = await undoApi.listSnapshots(sessionId)
        const target = snapshots.snapshots.find(
          (snapshot) => snapshot.description !== 'Session start',
        )
        if (!target) {
          showToast('Nothing to undo — the latest rating was already undone.', 'info')
          return false
        }
        await undoApi.undo(sessionId, target.id)
        await invalidateAfterUndo(queryClient, sessionId)
        showToast('Rating undone. Roll and History are up to date.', 'success')
        return true
      } catch (error: unknown) {
        console.error('Failed to undo latest rating:', getApiErrorDetail(error))
        showToast('Undo failed. Nothing was changed.', 'error')
        return false
      } finally {
        setIsPending(false)
      }
    },
    [showToast],
  )

  return { undoLatest, isPending }
}
