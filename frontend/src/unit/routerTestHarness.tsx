import { useEffect, type ReactNode } from 'react'
import { MemoryRouter, useLocation } from 'react-router-dom'

/**
 * Records every pathname the wrapped tree navigates to.
 */
export type RouterHarness = {
  /** Pathnames observed after navigation, in order, deduplicated per mount. */
  navigations: string[]
  /** Wrapper component to hand to `render` or `renderHook`. */
  wrapper: (props: { children: ReactNode }) => ReactNode
  /** Reset recorded navigations between assertions. */
  reset: () => void
}

/**
 * Build a real in-memory router harness that records navigation targets.
 *
 * Components under test use the actual `useNavigate`, so navigation is
 * exercised through react-router instead of a replaced hook.
 *
 * @param initialEntries - Starting history entries for the router.
 * @returns The recorded navigations plus a render wrapper.
 */
export function createRouterHarness(initialEntries: string[] = ['/']): RouterHarness {
  const navigations: string[] = []

  function LocationRecorder() {
    const location = useLocation()
    useEffect(() => {
      navigations.push(location.pathname)
    }, [location.pathname])
    return null
  }

  function RouterWrapper({ children }: { children: ReactNode }) {
    return (
      <MemoryRouter initialEntries={initialEntries}>
        <LocationRecorder />
        {children}
      </MemoryRouter>
    )
  }

  return {
    navigations,
    wrapper: RouterWrapper,
    reset: () => {
      navigations.length = 0
    },
  }
}
