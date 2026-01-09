import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { undoApi } from '../services/api'

export function useSnapshots(sessionId) {
  return useQuery({
    queryKey: ['undo', sessionId, 'snapshots'],
    queryFn: () => undoApi.listSnapshots(sessionId),
    enabled: !!sessionId,
  })
}

export function useUndo() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ sessionId, snapshotId }) => undoApi.undo(sessionId, snapshotId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['session'] })
      queryClient.invalidateQueries({ queryKey: ['threads'] })
      queryClient.invalidateQueries({ queryKey: ['sessions'] })
    },
  })
}
