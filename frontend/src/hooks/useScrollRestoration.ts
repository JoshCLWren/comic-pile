import { useCallback, useEffect, useRef } from 'react'
import { useLocation, useNavigationType } from 'react-router-dom'
import {
  beginRouteRestore,
  restoreRouteScrollPosition,
  waitForLayoutSettled,
} from '../scroll/scrollCoordinator'

const SESSION_STORAGE_KEY = 'comic-pile:scroll-positions'

type ScrollPositions = Record<string, number>

function readStore(): ScrollPositions {
  if (typeof sessionStorage === 'undefined') {
    return {}
  }
  try {
    const raw = sessionStorage.getItem(SESSION_STORAGE_KEY)
    // SAFETY: the JSON was written by writeStore from a Record<string, number>, so parse yields that shape.
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
 *
 * Scroll ownership (#2582): this hook is the sole owner of route/resume
 * restoration. All viewport writes flow through the shared scroll
 * coordinator (`restoreRouteScrollPosition`), restoration settles against an
 * explicit layout-readiness contract (`waitForLayoutSettled`) rather than a
 * guessed delay, and feature semantic scrolling defers while a restore is
 * actively settling.
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
      if ('requestAnimationFrame' in window) {
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
  // The target is applied immediately, then re-applied while deferred layout
  // is still shifting: late renders can grow the scrollable area and unclamp
  // a restore that the browser clamped on the first pass. The settle loop is
  // an explicit readiness contract (stable layout frames) — never a fixed
  // timeout. A user-driven gesture (wheel / touch / keys) ends the watch so
  // restoration never fights an intentional scroll.
  useEffect(() => {
    if (typeof window === 'undefined') {
      return
    }
    // Back/forward and reloads return to the prior position; new screens start at the top.
    const saved = readStore()[pathname] ?? 0
    const target = navType === 'POP' ? saved : 0
    const endRestore = beginRouteRestore()
    let cancelled = false
    let userMoved = false
    const markUserMoved = () => {
      userMoved = true
    }

    const applyRestore = () => {
      if (typeof document !== 'undefined' && document.visibilityState !== 'visible') {
        return
      }
      restoreRouteScrollPosition(target)
    }

    if (!('requestAnimationFrame' in window)) {
      applyRestore()
      endRestore()
      return endRestore
    }
    const raf = window.requestAnimationFrame(() => {
      if (cancelled) {
        return
      }
      applyRestore()
      void waitForLayoutSettled({
        isCancelled: () => cancelled || userMoved,
        needsReapply: () =>
          !userMoved && !cancelled && typeof window !== 'undefined' && window.scrollY !== target,
        reapply: applyRestore,
      }).then(() => {
        endRestore()
      })
    })
    if (typeof window !== 'undefined') {
      window.addEventListener('wheel', markUserMoved, { passive: true })
      window.addEventListener('touchmove', markUserMoved, { passive: true })
      window.addEventListener('keydown', markUserMoved)
    }
    return () => {
      cancelled = true
      if ('cancelAnimationFrame' in window) {
        window.cancelAnimationFrame(raf)
      }
      if (typeof window !== 'undefined') {
        window.removeEventListener('wheel', markUserMoved)
        window.removeEventListener('touchmove', markUserMoved)
        window.removeEventListener('keydown', markUserMoved)
      }
      endRestore()
    }
  }, [currentKey, navType, pathname])

  // Restore immediately when returning to a backgrounded or restored tab.
  // Owned by the same restoration contract: the viewport write flows through
  // the coordinator so resume recovery (data-only) can never race it.
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
      const endRestore = beginRouteRestore()
      restoreRouteScrollPosition(saved)
      endRestore()
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
