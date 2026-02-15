import { useState, useEffect } from 'react'
import { tasksApi } from '../services/api'

export interface RecentSession {
  id: number
  start_die: number
  started_at: string
  ended_at: string | null
}

export interface TopRatedThread {
  id: number
  title: string
  rating: number
  format: string | null
}

interface EventStats {
  [eventType: string]: number
}

interface MetricsData {
  total_threads: number
  active_threads: number
  completed_threads: number
  completion_rate: number
  average_session_hours: number
  recent_sessions: RecentSession[]
  event_stats: EventStats
  top_rated_threads: TopRatedThread[]
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
