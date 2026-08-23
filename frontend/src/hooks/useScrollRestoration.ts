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
    if (typeof window === 'undefined') {
      return
    }
    const store = readStore()
    store[pathname] = window.scrollY
    writeStore(store)
  }, [pathname])

  // Capture the live scroll position for the active screen.
  useEffect(() => {
    if (typeof window === 'undefined') {
      return
    }
    const handleScroll = () => {
      if (saveScheduled.current) {
        return
      }
      saveScheduled.current = true
      if (typeof window !== 'undefined' && typeof window.requestAnimationFrame === 'function') {
        window.requestAnimationFrame(() => {
          saveScheduled.current = false
          saveCurrentScroll()
        })
      } else {
        saveScheduled.current = false
        saveCurrentScroll()
      }
    }
    const handleHide = () => saveCurrentScroll()
    const handleVisibility = () => {
      if (typeof document !== 'undefined' && document.visibilityState === 'hidden') {
        saveCurrentScroll()
      }
    }
    if (typeof window !== 'undefined') {
      window.addEventListener('scroll', handleScroll, { passive: true })
      window.addEventListener('pagehide', handleHide)
    }
    if (typeof document !== 'undefined') {
      document.addEventListener('visibilitychange', handleVisibility)
    }
    return () => {
      if (typeof window !== 'undefined') {
        window.removeEventListener('scroll', handleScroll)
        window.removeEventListener('pagehide', handleHide)
      }
      if (typeof document !== 'undefined') {
        document.removeEventListener('visibilitychange', handleVisibility)
      }
    }
  }, [saveCurrentScroll])

  // Restore on navigation (including the initial load / reload).
  useEffect(() => {
    if (typeof window === 'undefined') {
      return
    }
    const restore = () => {
      if (typeof document !== 'undefined' && document.visibilityState !== 'visible') {
        return
      }
      if (typeof window === 'undefined') {
        return
      }
      const saved = readStore()[pathname] ?? 0
      // Back/forward and reloads return to the prior position; new screens start at the top.
      window.scrollTo(0, navType === 'POP' ? saved : 0)
    }

    if (typeof window.requestAnimationFrame !== 'function') {
      restore()
      return
    }
    const raf = window.requestAnimationFrame(() => {
      restore()
      // Late layout (deferred data renders) can shrink the scrollable area and
      // clamp the restored offset; re-apply once the screen has settled.
      if (navType === 'POP' && typeof window.setTimeout === 'function') {
        window.setTimeout(restore, 150)
      } else if (navType === 'POP' && typeof setTimeout === 'function') {
        // Fallback when window is gone but global setTimeout survives teardown
        setTimeout(restore, 150)
      }
    })
    return () => {
      if (typeof window !== 'undefined' && typeof window.cancelAnimationFrame === 'function') {
        window.cancelAnimationFrame(raf)
      }
    }
  }, [currentKey, navType, pathname])

  // Restore immediately when returning to a backgrounded or restored tab.
  useEffect(() => {
    if (typeof window === 'undefined') {
      return
    }
    const handleVisible = () => {
      if (typeof document !== 'undefined' && document.visibilityState !== 'visible') {
        return
      }
      if (typeof window === 'undefined') {
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
      if (typeof window !== 'undefined') {
        window.removeEventListener('pageshow', handlePageShow)
      }
    }
  }, [pathname])
}
