import { useEffect, useState } from 'react'

export function useIsDesktop(breakpoint = 1024): boolean {
  const getInitial = (): boolean => {
    if (typeof window === 'undefined') return true
    if (typeof window.matchMedia !== 'function') return window.innerWidth >= breakpoint
    return window.matchMedia(`(min-width: ${breakpoint}px)`).matches
  }

  const [isDesktop, setIsDesktop] = useState(getInitial)

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return
    const mql = window.matchMedia(`(min-width: ${breakpoint}px)`)
    setIsDesktop(mql.matches)
    const handler = (event: MediaQueryListEvent) => setIsDesktop(event.matches)
    mql.addEventListener('change', handler)
    return () => mql.removeEventListener('change', handler)
  }, [breakpoint])

  return isDesktop
}
