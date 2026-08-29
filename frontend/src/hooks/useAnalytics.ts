import { useQuery } from '@tanstack/react-query'
import { tasksApi } from '../services/api'
import { queryKeys } from '../query/queryKeys'

export function useAnalytics() {
  const { data, isPending, isError } = useQuery({
    queryKey: queryKeys.analytics.overview(),
    queryFn: () => tasksApi.getMetrics(),
  })

  return { data: data ?? null, isLoading: isPending, error: isError ? new Error('Failed to load analytics') : null }
}
