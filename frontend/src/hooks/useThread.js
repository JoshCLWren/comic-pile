import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { threadsApi } from '../services/api'

export function useThreads() {
  return useQuery({
    queryKey: ['threads'],
    queryFn: () => threadsApi.list(),
  })
}

export function useThread(id) {
  return useQuery({
    queryKey: ['thread', id],
    queryFn: () => threadsApi.get(id),
    enabled: !!id,
  })
}

export function useStaleThreads(days = 30) {
  return useQuery({
    queryKey: ['threads', 'stale', days],
    queryFn: () => threadsApi.listStale(days),
  })
}

export function useCreateThread() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (data) => threadsApi.create(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['threads'] })
    },
  })
}

export function useUpdateThread() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ id, data }) => threadsApi.update(id, data),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['thread', variables.id] })
      queryClient.invalidateQueries({ queryKey: ['threads'] })
    },
  })
}

export function useDeleteThread() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (id) => threadsApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['threads'] })
    },
  })
}

export function useReactivateThread() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (data) => threadsApi.reactivate(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['threads'] })
    },
  })
}
