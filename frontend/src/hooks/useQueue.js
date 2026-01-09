import { useMutation, useQueryClient } from '@tanstack/react-query'
import { queueApi } from '../services/api'

export function useMoveToPosition() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ id, position }) => queueApi.moveToPosition(id, position),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['threads'] })
    },
  })
}

export function useMoveToFront() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (id) => queueApi.moveToFront(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['threads'] })
    },
  })
}

export function useMoveToBack() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (id) => queueApi.moveToBack(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['threads'] })
    },
  })
}
