import { useQuery } from '@tanstack/react-query'
import { tasksApi } from '../services/api'
import { queryKeys } from '../query/queryKeys'
import type { AnalyticsMetrics } from '../types'

export function useAnalytics() {
  const { data, isPending, error } = useQuery({
    queryKey: queryKeys.analytics.overview(),
    queryFn: async () => {
      try {
        return await tasksApi.getMetrics()
      } catch (err) {
        throw err instanceof Error ? err : new Error(String(err))
      }
    },
  })

  return {
    data: data ?? null,
    isLoading: isPending,
    error: (error as Error | null) ?? null,
  }
}
