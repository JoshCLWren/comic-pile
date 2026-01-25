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
      queryClient.invalidateQueries({ queryKey: ['session', 'current'] })
      queryClient.invalidateQueries({ queryKey: ['threads'] })
      navigate('/roll')
    },
  })
}
