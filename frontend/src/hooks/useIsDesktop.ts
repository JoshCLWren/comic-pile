import { useEffect, useState } from 'react'

export function useIsDesktop(breakpoint = 1024): boolean {
  const [isDesktop, setIsDesktop] = useState(() => {
    if (typeof window !== 'undefined') return window.innerWidth >= breakpoint
    return true
  })

  useEffect(() => {
    const mql = window.matchMedia(`(min-width: ${breakpoint}px)`)
    setIsDesktop(mql.matches)
    const handler = (event: MediaQueryListEvent) => setIsDesktop(event.matches)
    mql.addEventListener('change', handler)
    return () => mql.removeEventListener('change', handler)
  }, [breakpoint])

  return isDesktop
}