import { useEffect, useRef } from 'react'

const PING_INTERVAL_MS = 4 * 60 * 1000

export function usePingHeartbeat() {
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    const sendPing = () => {
      if (document.visibilityState === 'visible') {
        void fetch('/api/ping', { method: 'GET', cache: 'no-store' }).catch(() => {})
      }
    }

    const startInterval = () => {
      if (intervalRef.current !== null) return
      sendPing()
      intervalRef.current = setInterval(sendPing, PING_INTERVAL_MS)
    }

    const stopInterval = () => {
      if (intervalRef.current !== null) {
        clearInterval(intervalRef.current)
        intervalRef.current = null
      }
    }

    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        startInterval()
      } else {
        stopInterval()
      }
    }

    document.addEventListener('visibilitychange', handleVisibilityChange)

    if (document.visibilityState === 'visible') {
      startInterval()
    }

    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange)
      stopInterval()
    }
  }, [])
}
