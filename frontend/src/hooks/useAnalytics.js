import { useState, useEffect } from 'react'
import { tasksApi } from '../services/api'

export function useAnalytics() {
  const [data, setData] = useState(null)
  const [isPending, setIsPending] = useState(true)
  const [isError, setIsError] = useState(false)

  useEffect(() => {
    async function fetchMetrics() {
      try {
        setIsPending(true)
        setIsError(false)
        const metrics = await tasksApi.getMetrics()
        setData(metrics)
      } catch {
        setIsError(true)
      } finally {
        setIsPending(false)
      }
    }

    fetchMetrics()
  }, [])

  return { data, isPending, isError }
}
