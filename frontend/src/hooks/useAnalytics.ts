import { useState, useEffect } from 'react'
import { tasksApi } from '../services/api'

interface MetricsData {
  total_threads: number
  completed_threads: number
  average_rating: number
}

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
