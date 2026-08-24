import { useQuery } from '@tanstack/react-query'
import { tasksApi } from '../services/api'
import { queryKeys } from '../query/queryKeys'

export function useAnalytics() {
  const query = useQuery({
    queryKey: queryKeys.analytics.overview(),
    queryFn: () => tasksApi.getMetrics(),
    staleTime: 30_000,
    retry: false,
  })

  return {
    data: query.data ?? null,
    isLoading: query.isLoading,
    error: query.error ?? null,
  }
}
