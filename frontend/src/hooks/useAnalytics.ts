import { useState, useEffect } from 'react'
import { tasksApi, type MetricsData } from '../services/api'

// Re-export types from MetricsData
export type RecentSession = MetricsData['recent_sessions'][number]
export type TopRatedThread = MetricsData['top_rated_threads'][number]
export type { MetricsData }

export function useAnalytics() {
  const [data, setData] = useState<MetricsData | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<Error | null>(null)

  useEffect(() => {
    async function fetchMetrics() {
      try {
        setIsLoading(true)
        setError(null)
        const metrics = await tasksApi.getMetrics()
        setData(metrics)
      } catch (err) {
        setError(err as Error)
      } finally {
        setIsLoading(false)
      }
    }

    fetchMetrics()
  }, [])

  return { data, isLoading, error }
}
