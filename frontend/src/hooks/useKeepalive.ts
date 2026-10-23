import { useCallback, useEffect, useRef, useState } from 'react'
import api from '../services/api'

// Configuration constants
const KEEPALIVE_INTERVAL_MS = 4 * 60 * 1000 // 4 minutes (just under Neon's ~5 min suspend)
const ACTIVITY_TIMEOUT_MS = 5 * 60 * 1000 // 5 minutes of inactivity before stopping keepalive
const PREWARM_DEBOUNCE_MS = 1000 // Debounce rapid visibility changes

// Activity event types that count as user activity
const ACTIVITY_EVENTS = [
  'mousedown',
  'mousemove',
  'keydown',
  'touchstart',
  'scroll',
  'wheel',
] as const

type ActivityEventType = (typeof ACTIVITY_EVENTS)[number]

export function useKeepalive(enabled = true) {
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const prewarmTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const lastActivityRef = useRef<number>(Date.now())
  const isVisibleRef = useRef<boolean>(!document.hidden)
  const isPrewarmingRef = useRef<boolean>(false)
  const [isWarming, setIsWarming] = useState(false)

  // Update last activity timestamp
  const handleActivity = useCallback(() => {
    lastActivityRef.current = Date.now()
  }, [])

  // Check if user is considered active (activity within timeout)
  const isUserActive = useCallback(() => {
    return Date.now() - lastActivityRef.current < ACTIVITY_TIMEOUT_MS
  }, [])

  // Call the keepalive endpoint
  const callKeepalive = useCallback(async (isPrewarm = false) => {
    if (!enabled) return

    if (isPrewarm) {
      if (isPrewarmingRef.current) return
      isPrewarmingRef.current = true
    } else {
      setIsWarming(true)
    }

    try {
      await api.get('/api/keepalive', { timeout: 5000 })
    } catch (error) {
      // Silently ignore keepalive failures - they're best-effort
      console.debug('Keepalive ping failed:', error)
    } finally {
      if (isPrewarm) {
        isPrewarmingRef.current = false
      } else {
        setIsWarming(false)
      }
    }
  }, [enabled])

  // Stop the periodic keepalive interval
  const stopInterval = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current)
      intervalRef.current = null
    }
  }, [])

  // Start the periodic keepalive interval
  const startInterval = useCallback(() => {
    if (intervalRef.current) return // Already running

    intervalRef.current = setInterval(() => {
      if (isVisibleRef.current && isUserActive()) {
        void callKeepalive(false)
      } else {
        // Stop interval if tab hidden or user inactive
        stopInterval()
      }
    }, KEEPALIVE_INTERVAL_MS)
  }, [callKeepalive, isUserActive, stopInterval])

  // Handle visibility change
  const handleVisibilityChange = useCallback(() => {
    const nowVisible = !document.hidden
    isVisibleRef.current = nowVisible

    if (nowVisible) {
      // Tab became visible - prewarm immediately (debounced)
      if (prewarmTimeoutRef.current) {
        clearTimeout(prewarmTimeoutRef.current)
      }
      prewarmTimeoutRef.current = setTimeout(() => {
        if (!document.hidden && isUserActive()) {
          void callKeepalive(true)
          startInterval()
        }
      }, PREWARM_DEBOUNCE_MS)
    } else {
      // Tab became hidden - stop keepalive
      stopInterval()
      if (prewarmTimeoutRef.current) {
        clearTimeout(prewarmTimeoutRef.current)
        prewarmTimeoutRef.current = null
      }
    }
  }, [callKeepalive, isUserActive, startInterval, stopInterval])

  // Set up event listeners
  useEffect(() => {
    if (!enabled) return

    // Initialize last activity time
    lastActivityRef.current = Date.now()
    isVisibleRef.current = !document.hidden

    // Add activity listeners
    ACTIVITY_EVENTS.forEach((event) => {
      document.addEventListener(event, handleActivity, { passive: true })
    })

    // Add visibility listener
    document.addEventListener('visibilitychange', handleVisibilityChange)

    // Start interval if initially visible and active
    if (isVisibleRef.current && isUserActive()) {
      startInterval()
    }

    return () => {
      // Clean up
      stopInterval()
      if (prewarmTimeoutRef.current) {
        clearTimeout(prewarmTimeoutRef.current)
      }
      ACTIVITY_EVENTS.forEach((event) => {
        document.removeEventListener(event, handleActivity)
      })
      document.removeEventListener('visibilitychange', handleVisibilityChange)
    }
  }, [enabled, handleActivity, handleVisibilityChange, isUserActive, startInterval, stopInterval])

  return {
    isWarming,
    isActive: isUserActive(),
    isVisible: isVisibleRef.current,
  }
}