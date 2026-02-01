import { useState, useEffect } from 'react'
import { tasksApi } from '../services/api'

export function useAnalytics() {
  const [data, setData] = useState(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    async function fetchMetrics() {
      try {
        setIsLoading(true)
        setError(null)
        const metrics = await tasksApi.getMetrics()
        setData(metrics)
      } catch (err) {
        setError(err)
      } finally {
        setIsLoading(false)
      }
    }

    fetchMetrics()
  }, [])

  return { data, isLoading, error }
}
