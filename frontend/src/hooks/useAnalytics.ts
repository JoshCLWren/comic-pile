import { useQuery } from '@tanstack/react-query'
import { tasksApi } from '../services/api'
import { queryKeys } from '../query/queryKeys'
import type { AnalyticsMetrics } from '../types'

/** Contract for the analytics service dependency consumed by `useAnalytics`. */
export interface AnalyticsTasksApi {
  getMetrics: () => Promise<AnalyticsMetrics>
}

function resolveTasksApi(api?: AnalyticsTasksApi): AnalyticsTasksApi {
  return api ?? tasksApi
}

export function useAnalytics(api?: AnalyticsTasksApi) {
  const tasksApiInstance = resolveTasksApi(api)
  const { data, isPending, error } = useQuery({
    queryKey: queryKeys.analytics.overview(),
    queryFn: async () => {
      try {
        return await tasksApiInstance.getMetrics()
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
