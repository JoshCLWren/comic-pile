import { useEffect } from 'react'
import { useLocation } from 'react-router-dom'
import { scheduleRoutePrefetch } from '../query/routePrefetch'

/**
 * Warm retained route chunks for the likely next navigation from the current
 * screen. Scheduling is cancelled on unmount and on every pathname change so
 * the prefetch never competes with an actual navigation.
 */
export function useRoutePrefetch(enabled: boolean): void {
  const { pathname } = useLocation()

  useEffect(() => {
    if (!enabled) return undefined
    return scheduleRoutePrefetch(pathname)
  }, [enabled, pathname])
}
