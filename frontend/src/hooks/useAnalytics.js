import { useQuery } from '@tanstack/react-query'
import { tasksApi } from '../services/api'

export function useAnalytics() {
  return useQuery({
    queryKey: ['tasks', 'metrics'],
    queryFn: () => tasksApi.getMetrics(),
    refetchInterval: 30000,
  })
}