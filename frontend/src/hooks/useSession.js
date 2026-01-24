import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { sessionApi } from '../services/api'

export function useSession() {
  return useQuery({
    queryKey: ['session'],
    queryFn: () => sessionApi.getCurrent(),
    refetchInterval: 5000,
  })
}

export function useSessions(params = {}) {
  return useQuery({
    queryKey: ['sessions', params],
    queryFn: () => sessionApi.list(params),
  })
}

export function useSessionDetails(id) {
  return useQuery({
    queryKey: ['session', id, 'details'],
    queryFn: () => sessionApi.getDetails(id),
    enabled: !!id,
  })
}

export function useSessionSnapshots(id) {
  return useQuery({
    queryKey: ['session', id, 'snapshots'],
    queryFn: () => sessionApi.getSnapshots(id),
    enabled: !!id,
  })
}

export function useRestoreSessionStart() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (sessionId) => sessionApi.restoreSessionStart(sessionId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['session'] })
      queryClient.invalidateQueries({ queryKey: ['sessions'] })
      queryClient.invalidateQueries({ queryKey: ['threads'] })
    },
    onError: (error) => {
      console.error('Failed to restore session:', error.response?.data?.detail || error.message)
    },
  })
}
