import { useEffect, useRef } from 'react'

const POLL_INTERVAL_MS = 4 * 60 * 1000

export function usePingHeartbeat() {
  const timerRef = useRef<number | null>(null)

  useEffect(() => {
    const tick = async () => {
      try {
        await fetch('/api/ping', { method: 'GET' })
      } catch {
        // Ignore network errors to avoid poll disruption.
      }
    }

    const schedule = () => {
      if (document.visibilityState !== 'visible') {
        return
      }
      timerRef.current = window.setTimeout(async () => {
        await tick()
        schedule()
      }, POLL_INTERVAL_MS)
    }

    const onVisibilityChange = () => {
      if (timerRef.current !== null) {
        window.clearTimeout(timerRef.current)
        timerRef.current = null
      }
      if (document.visibilityState === 'visible') {
        schedule()
      }
    }

    document.addEventListener('visibilitychange', onVisibilityChange)
    schedule()

    return () => {
      document.removeEventListener('visibilitychange', onVisibilityChange)
      if (timerRef.current !== null) {
        window.clearTimeout(timerRef.current)
        timerRef.current = null
      }
    }
  }, [])
}
