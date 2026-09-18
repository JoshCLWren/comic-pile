/**
 * Canonical responsive contract for Comic Pile.
 *
 * Tailwind's breakpoint contract is canonical:
 * - md = 768px
 * - lg = 1024px
 * - xl = 1280px
 *
 * Components must not hard-code responsive behavior with direct
 * `window.innerWidth` comparisons. Use the hooks and constants
 * in this module instead.
 */

import { useEffect, useRef, useState } from 'react'

/** Canonical breakpoint values matching Tailwind's md/lg/xl. */
export const BREAKPOINTS = {
  md: 768,
  lg: 1024,
  xl: 1280,
} as const

/** Maximum width for the mobile band (below md). */
export const MOBILE_MAX_WIDTH = BREAKPOINTS.md - 1 // 767

/** Maximum width for the tablet portrait band (md to just below lg). */
export const TABLET_MAX_WIDTH = BREAKPOINTS.lg - 1 // 1023

/** Media query matching the tablet portrait band (md through just below lg). */
const TABLET_QUERY = `(min-width: ${BREAKPOINTS.md}px) and (max-width: ${TABLET_MAX_WIDTH}px)`

/**
 * Returns whether `matchMedia` is available in the current environment.
 */
function hasMatchMedia(): boolean {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function'
}

/**
 * Resolve whether a given CSS media query matches.
 * Returns `false` in SSR or when matchMedia is unavailable.
 */
function matchMediaMatches(query: string): boolean {
  if (!hasMatchMedia()) return false
  try {
    return window.matchMedia(query).matches
  } catch {
    return false
  }
}

/**
 * A reactive hook that tracks whether a CSS media query matches.
 *
 * Uses `window.matchMedia` with a listener for live updates, falling
 * back to a one-time check if the listener API is unavailable.
 */
export function useMatchMedia(query: string): boolean {
  const [matches, setMatches] = useState<boolean>(() => matchMediaMatches(query))
  const queryRef = useRef(query)

  useEffect(() => {
    queryRef.current = query
    if (!hasMatchMedia()) return

    const mql = window.matchMedia(query)
    const handler = (event: MediaQueryListEvent) => setMatches(event.matches)

    if (mql.addEventListener) {
      mql.addEventListener('change', handler)
      return () => mql.removeEventListener('change', handler)
    }
    if ((mql as unknown as { addListener?: (l: (e: MediaQueryListEvent) => void) => void }).addListener) {
      const listener = (event: MediaQueryListEvent) => setMatches(event.matches)
      ;(mql as unknown as { addListener: (l: typeof listener) => void }).addListener(listener)
      return () => (mql as unknown as { removeListener: (l: typeof listener) => void }).removeListener(listener)
    }

    const onResize = () => setMatches(matchMediaMatches(queryRef.current))
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [query])

  return matches
}

/**
 * A reactive hook that returns the current responsive band based on
 * the canonical breakpoint contract.
 *
 * - `isMobile`: viewport below 768px (mobile band)
 * - `isTablet`: viewport 768px through 1023px (tablet portrait band)
 * - `isDesktop`: viewport 1024px and above (desktop band)
 */
export function useResponsive() {
  const isMobile = useMatchMedia(`(max-width: ${MOBILE_MAX_WIDTH}px)`)
  const isTablet = useMatchMedia(TABLET_QUERY)
  const isDesktop = useMatchMedia(`(min-width: ${BREAKPOINTS.lg}px)`)

  return { isMobile, isTablet, isDesktop }
}

/**
 * Determine the default nav-collapse state for a given viewport width,
 * based on the canonical contract:
 * - below 768: mobile chrome → not collapsed
 * - 768 through 1023: tablet/desktop chrome → collapsed by default
 * - 1024+: desktop chrome → not collapsed
 *
 * This is a pure function suitable for useState initializers.
 */
export function getDefaultCollapsedForWidth(width: number): boolean {
  if (width < BREAKPOINTS.md) return false
  if (width < BREAKPOINTS.lg) return true
  return false
}

/**
 * Determine the default nav-collapse state using the shared `matchMedia`
 * abstraction. Returns `false` in SSR or when `matchMedia` is unavailable.
 */
export function getDefaultCollapsed(): boolean {
  return matchMediaMatches(TABLET_QUERY)
}
