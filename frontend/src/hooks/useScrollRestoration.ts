import { useCallback, useEffect, useRef } from 'react'
import { useLocation, useNavigationType } from 'react-router-dom'

const SESSION_STORAGE_KEY = 'comic-pile:scroll-positions'

type ScrollPositions = Record<string, number>

function readStore(): ScrollPositions {
  if (typeof sessionStorage === 'undefined') {
    return {}
  }
  try {
    const raw = sessionStorage.getItem(SESSION_STORAGE_KEY)
    return raw ? (JSON.parse(raw) as ScrollPositions) : {}
  } catch {
    return {}
  }
}

function writeStore(store: ScrollPositions): void {
  if (typeof sessionStorage === 'undefined') {
    return
  }
  try {
    sessionStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(store))
  } catch {
    // Storage may be unavailable (private mode); restoration is best-effort.
  }
}

/**
 * Keep the user on the same part of the screen they left.
 *
 * Restores window scroll on back/forward navigation and when returning to a
 * backgrounded or reloaded screen, and scrolls to the top when opening a new
 * screen. Positions are tracked per pathname so a return to the app lands the
 * user exactly where they were instead of at the top of the page.
 */
export function useScrollRestoration(): void {
  const location = useLocation()
  const navType = useNavigationType()
  const currentKey = location.key || 'default'
  const pathname = location.pathname
  const saveScheduled = useRef(false)

  const saveCurrentScroll = useCallback(() => {
    const store = readStore()
    store[pathname] = window.scrollY
    writeStore(store)
  }, [pathname])

  // Capture the live scroll position for the active screen.
  useEffect(() => {
    const handleScroll = () => {
      if (saveScheduled.current) {
        return
      }
      saveScheduled.current = true
      window.requestAnimationFrame(() => {
        saveScheduled.current = false
        saveCurrentScroll()
      })
    }
    const handleHide = () => saveCurrentScroll()
    const handleVisibility = () => {
      if (typeof document !== 'undefined' && document.visibilityState === 'hidden') {
        saveCurrentScroll()
      }
    }
    window.addEventListener('scroll', handleScroll, { passive: true })
    window.addEventListener('pagehide', handleHide)
    if (typeof document !== 'undefined') {
      document.addEventListener('visibilitychange', handleVisibility)
    }
    return () => {
      window.removeEventListener('scroll', handleScroll)
      window.removeEventListener('pagehide', handleHide)
      if (typeof document !== 'undefined') {
        document.removeEventListener('visibilitychange', handleVisibility)
      }
    }
  }, [saveCurrentScroll])

  // Restore on navigation (including the initial load / reload).
  useEffect(() => {
    const restore = () => {
      if (typeof document !== 'undefined' && document.visibilityState !== 'visible') {
        return
      }
      const saved = readStore()[pathname] ?? 0
      // Back/forward and reloads return to the prior position; new screens start at the top.
      window.scrollTo(0, navType === 'POP' ? saved : 0)
    }

    const raf = window.requestAnimationFrame(() => {
      restore()
      // Late layout (deferred data renders) can shrink the scrollable area and
      // clamp the restored offset; re-apply once the screen has settled.
      if (navType === 'POP') {
        window.setTimeout(restore, 150)
      }
    })
    return () => window.cancelAnimationFrame(raf)
  }, [currentKey, navType, pathname])

  // Restore immediately when returning to a backgrounded or restored tab.
  useEffect(() => {
    const handleVisible = () => {
      if (typeof document !== 'undefined' && document.visibilityState !== 'visible') {
        return
      }
      const saved = readStore()[pathname] ?? 0
      window.scrollTo(0, saved)
    }
    const handlePageShow = (event: PageTransitionEvent) => {
      if (event.persisted) {
        handleVisible()
      }
    }
    if (typeof document !== 'undefined') {
      document.addEventListener('visibilitychange', handleVisible)
    }
    window.addEventListener('pageshow', handlePageShow)
    return () => {
      if (typeof document !== 'undefined') {
        document.removeEventListener('visibilitychange', handleVisible)
      }
      window.removeEventListener('pageshow', handlePageShow)
    }
  }, [pathname])
}
