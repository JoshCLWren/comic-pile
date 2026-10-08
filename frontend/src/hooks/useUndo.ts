import { useCallback } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { undoApi } from '../services/api-undo'
import { getApiErrorDetail } from '../utils/apiError'
import { queryKeys } from '../query/queryKeys'
import { invalidateAfterQueueMutation } from '../query/cacheEffects'
import { useToast } from '../contexts/useToast'
import type { SessionSnapshotsResponse, UndoPayload } from '../types'

export function useSnapshots(sessionId: number | string | null | undefined) {
  const { data, isPending, isError, error } = useQuery({
    queryKey: sessionId != null ? queryKeys.undo.snapshots(sessionId) : [],
    queryFn: () => undoApi.listSnapshots(sessionId!),
    enabled: sessionId != null,
  })

  if (sessionId == null) {
    // SAFETY: no session id means no snapshots; null is the intentional shape when the query is disabled.
    return { data: null as SessionSnapshotsResponse | null, isPending: false, isError: false }
  }

  return { data: data ?? null, isPending, isError }
}

export function useUndo() {
  const queryClient = useQueryClient()
  const { showToast } = useToast()

  const mutation = useMutation({
    mutationFn: async ({ sessionId, snapshotId }: UndoPayload) => {
      await undoApi.undo(sessionId, snapshotId)
    },
    onSuccess: async () => {
      // Invalidate caches to reflect the undone state
      await invalidateAfterQueueMutation(queryClient)
      showToast('Rating undone', 'success')
    },
    onError: (error: unknown) => {
      console.error('Failed to undo action:', getApiErrorDetail(error))
      showToast('Failed to undo rating', 'error')
    },
  })

  return {
    mutate: mutation.mutateAsync,
    isPending: mutation.isPending,
    isError: mutation.isError,
  }
}
