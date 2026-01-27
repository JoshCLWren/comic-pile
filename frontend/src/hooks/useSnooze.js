import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { snoozeApi } from '../services/api'

export function useSnooze() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()

  return useMutation({
    mutationFn: () => snoozeApi.snooze(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['session'] })
      queryClient.invalidateQueries({ queryKey: ['threads'] })
      navigate('/')
    },
  })
}

export function useUnsnooze() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (threadId) => snoozeApi.unsnooze(threadId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['session'] })
    },
  })
}
