import { useMutation, useQueryClient } from '@tanstack/react-query'
import { queueApi } from '../services/api'

export function useMoveToPosition() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ id, position }) => queueApi.moveToPosition(id, position),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['threads'] })
    },
    onError: (error) => {
      console.error('Failed to move thread to position:', error.response?.data?.detail || error.message)
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
    onError: (error) => {
      console.error('Failed to move thread to front:', error.response?.data?.detail || error.message)
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
    onError: (error) => {
      console.error('Failed to move thread to back:', error.response?.data?.detail || error.message)
    },
  })
}
