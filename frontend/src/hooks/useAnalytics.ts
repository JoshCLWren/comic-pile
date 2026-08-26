import { useQuery } from '@tanstack/react-query'
import { tasksApi } from '../services/api'
import { queryKeys } from '../query/queryKeys'
import type { AnalyticsMetrics } from '../types'

export function useAnalytics() {
  const query = useQuery({
    queryKey: queryKeys.analytics.overview(),
    queryFn: async () => {
      return tasksApi.getMetrics()
    },
    staleTime: 30_000,
    retry: false,
  })

  return {
    data: query.data ?? null,
    isLoading: query.isLoading,
    error: query.error instanceof Error ? query.error : query.error ? new Error(String(query.error)) : null,
  }
}