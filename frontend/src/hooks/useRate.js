import { useMutation, useQueryClient } from '@tanstack/react-query'
import { rateApi } from '../services/api'

export function useRate() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (data) => rateApi.rate(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['session'] })
      queryClient.invalidateQueries({ queryKey: ['threads'] })
    },
  })
}
