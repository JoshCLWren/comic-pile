import { useState, useEffect } from 'react'
import { tasksApi } from '../services/api'
import type { AnalyticsMetrics } from '../types'

export function useAnalytics() {
  const [data, setData] = useState<AnalyticsMetrics | null>(null)
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
        setError(err instanceof Error ? err : new Error(String(err)))
      } finally {
        setIsLoading(false)
      }
    }

    fetchMetrics()
  }, [])

  return { data, isLoading, error }
}
