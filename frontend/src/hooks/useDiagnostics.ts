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

interface ConsoleWithPatchedError {
  error: (...args: unknown[]) => void
}
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
