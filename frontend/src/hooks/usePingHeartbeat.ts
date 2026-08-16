import { useEffect, useRef, useCallback } from 'react'
import api from '../services/api'

const PING_INTERVAL_MS = 4 * 60 * 1000 // 4 minutes

/**
 * usePingHeartbeat - React hook that pings /api/ping every 4 minutes
 * when the browser tab is actively visible (document.visibilityState === 'visible').
 * Stops polling when tab is backgrounded/minimized to avoid burning
 * Vercel monthly execution quotas.
 */
export function usePingHeartbeat(): void {
  const intervalRef = useRef<number | null>(null)
  const isVisibleRef = useRef(true)

  const ping = useCallback(async (): Promise<void> => {
    try {
      await api.get('/ping', { skipAuthRedirect: true, timeout: 5000 })
    } catch {
      // Silently ignore ping failures - this is a best-effort warm-up
    }
  }, [])

  const startPolling = useCallback((): void => {
    if (intervalRef.current !== null) return
    if (!isVisibleRef.current) return

    // Initial ping
    void ping()

    // Set up interval
    intervalRef.current = window.setInterval(() => {
      if (isVisibleRef.current) {
        void ping()
      }
    }, PING_INTERVAL_MS)
  }, [ping])

  const stopPolling = useCallback((): void => {
    if (intervalRef.current !== null) {
      window.clearInterval(intervalRef.current)
      intervalRef.current = null
    }
  }, [])

  const handleVisibilityChange = useCallback((): void => {
    isVisibleRef.current = document.visibilityState === 'visible'

    if (isVisibleRef.current) {
      startPolling()
    } else {
      stopPolling()
    }
  }, [startPolling, stopPolling])

  useEffect(() => {
    // Initial visibility state
    isVisibleRef.current = document.visibilityState === 'visible'

    if (isVisibleRef.current) {
      startPolling()
    }

    document.addEventListener('visibilitychange', handleVisibilityChange)

    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange)
      stopPolling()
    }
  }, [startPolling, stopPolling, handleVisibilityChange])
}