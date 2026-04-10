import { useEffect, useRef, useCallback } from 'react'

interface DiagnosticData {
  timestamp: string
  url: string
  userAgent: string
  screen: {
    width: number
    height: number
    pixelRatio: number
  }
  viewport: {
    width: number
    height: number
  }
  scroll: {
    x: number
    y: number
  }
  performance: {
    domContentLoaded: number | null
    loadComplete: number | null
  }
  errors: Array<{
    message: string
    timestamp: string
  }>
}

interface ConsoleError {
  message: string
  timestamp: string
}

const MAX_ERRORS = 20
const errorBuffer: ConsoleError[] = []
let originalConsoleError: (typeof console.error) | null = null
let mountCount = 0

export type { DiagnosticData }

export function useDiagnostics() {
  const isPatched = useRef(false)

  const getPerformanceTiming = useCallback((): { domContentLoaded: number | null; loadComplete: number | null } => {
    try {
      if (typeof performance === 'undefined' || !performance) {
        return { domContentLoaded: null, loadComplete: null }
      }

      const navEntry = performance.getEntriesByType('navigation')[0] as PerformanceNavigationTiming | undefined
      if (navEntry) {
        return {
          domContentLoaded: navEntry.domContentLoadedEventEnd,
          loadComplete: navEntry.loadEventEnd,
        }
      }

      return { domContentLoaded: null, loadComplete: null }
    } catch {
      return { domContentLoaded: null, loadComplete: null }
    }
  }, [])

  const collectDiagnostics = useCallback((): DiagnosticData => {
    const performanceTiming = getPerformanceTiming()

    return {
      timestamp: new Date().toISOString(),
      url: typeof window !== 'undefined' ? window.location.href : '',
      userAgent: typeof navigator !== 'undefined' ? navigator.userAgent : '',
      screen: typeof window !== 'undefined' && window.screen ? {
        width: window.screen.width,
        height: window.screen.height,
        pixelRatio: typeof window !== 'undefined' ? window.devicePixelRatio || 1 : 1,
      } : {
        width: 0,
        height: 0,
        pixelRatio: 1,
      },
      viewport: typeof window !== 'undefined' ? {
        width: window.innerWidth,
        height: window.innerHeight,
      } : {
        width: 0,
        height: 0,
      },
      scroll: typeof window !== 'undefined' ? {
        x: window.scrollX,
        y: window.scrollY,
      } : {
        x: 0,
        y: 0,
      },
      performance: performanceTiming,
      errors: [...errorBuffer],
    }
  }, [getPerformanceTiming])

  useEffect(() => {
    mountCount++

    if (mountCount === 1 && typeof console !== 'undefined' && console.error && !isPatched.current) {
      const original = console.error
      originalConsoleError = original
      ;(console as unknown as Record<string, unknown>)['error'] = (...args: unknown[]) => {
        const timestamp = new Date().toISOString()
        const message = args.map((arg) => {
          if (typeof arg === 'string') return arg
          if (arg instanceof Error) return arg.message
          try {
            return JSON.stringify(arg)
          } catch {
            return String(arg)
          }
        }).join(' ')

        errorBuffer.push({ message, timestamp })
        if (errorBuffer.length > MAX_ERRORS) {
          errorBuffer.shift()
        }

        original(...args)
      }
      isPatched.current = true
    }

    return () => {
      mountCount--
      if (mountCount === 0 && originalConsoleError && typeof console !== 'undefined') {
        console.error = originalConsoleError
        isPatched.current = false
      }
    }
  }, [])

  return { collectDiagnostics }
}
