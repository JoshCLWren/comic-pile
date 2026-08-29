import { useQuery, useMutation } from '@tanstack/react-query'
import { undoApi } from '../services/api'
import { queryKeys } from '../query/queryKeys'
import type { UndoPayload } from '../types'

export function useSnapshots(sessionId: number | string | null | undefined) {
  const { data, isPending, isError } = useQuery({
    queryKey: sessionId ? queryKeys.undo.snapshots(sessionId) : [],
    queryFn: () => undoApi.listSnapshots(sessionId!),
    enabled: !!sessionId,
  })

  return { data: data ?? null, isPending, isError }
}

export function useUndo() {
  const mutation = useMutation({
    mutationFn: ({ sessionId, snapshotId }: UndoPayload) =>
      undoApi.undo(sessionId, snapshotId),
  })

  return {
    mutate: mutation.mutateAsync,
    isPending: mutation.isPending,
    isError: mutation.isError,
  }
}
