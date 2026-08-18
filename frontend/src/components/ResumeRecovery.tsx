import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import axios from 'axios'
import { queryClient } from '../query/queryClient'

const RESUME_REQUEST_TIMEOUT_MS = 15000
const RESUME_RETRY_DELAY_MS = 750
const MAX_RESUME_ATTEMPTS = 2
const SERVICE_UNAVAILABLE_MAX_ATTEMPTS = 10
const SERVICE_UNAVAILABLE_BASE_DELAY_MS = 1000
const RECONNECTING_UI_DELAY_MS = 3000
const SERVICE_UNAVAILABLE_RECONNECTING_UI_DELAY_MS = 8000

type RecoveryState = 'idle' | 'reconnecting' | 'failed'
type RecoveryMode = 'automatic' | 'explicit'

interface ResumeRecoveryProps {
  children: ReactNode
  revalidateSession: (timeout: number) => Promise<void>
  recoverSession: (timeout: number) => Promise<void>
}

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds))
}

function isServiceUnavailableError(error: unknown): boolean {
  return axios.isAxiosError(error) && error.response?.status === 503
}

export default function ResumeRecovery({
  children,
  revalidateSession,
  recoverSession,
}: ResumeRecoveryProps) {
  const [recoveryState, setRecoveryState] = useState<RecoveryState>('idle')
  const requestSequence = useRef(0)
  const lastValidationAt = useRef(0)
  const explicitRecoveryActive = useRef(false)
  const reconnectingTimer = useRef<number | undefined>()
  const lastErrorWasServiceUnavailable = useRef(false)

  const clearReconnectingTimer = useCallback(() => {
    if (reconnectingTimer.current !== undefined) {
      window.clearTimeout(reconnectingTimer.current)
      reconnectingTimer.current = undefined
    }
  }, [])

  const runRecovery = useCallback(async (mode: RecoveryMode) => {
    if (mode === 'automatic') {
      if (explicitRecoveryActive.current) {
        return
      }

      const now = Date.now()
      if (now - lastValidationAt.current < 1000) {
        return
      }
      lastValidationAt.current = now
    } else {
      explicitRecoveryActive.current = true
    }

    const sequence = ++requestSequence.current
    lastErrorWasServiceUnavailable.current = false
    clearReconnectingTimer()

    const recover = mode === 'explicit' ? recoverSession : revalidateSession
    const maxAttempts = mode === 'explicit' ? MAX_RESUME_ATTEMPTS : SERVICE_UNAVAILABLE_MAX_ATTEMPTS
    const baseDelay = mode === 'explicit' ? RESUME_RETRY_DELAY_MS : SERVICE_UNAVAILABLE_BASE_DELAY_MS
    const uiDelay = mode === 'explicit' ? RECONNECTING_UI_DELAY_MS : SERVICE_UNAVAILABLE_RECONNECTING_UI_DELAY_MS

    reconnectingTimer.current = window.setTimeout(() => {
      if (sequence === requestSequence.current) {
        setRecoveryState('reconnecting')
      }
    }, uiDelay)

    try {
      for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
        try {
          await recover(RESUME_REQUEST_TIMEOUT_MS)
          if (sequence !== requestSequence.current) {
            return
          }
          await queryClient.invalidateQueries()
          if (sequence !== requestSequence.current) {
            return
          }
          clearReconnectingTimer()
          setRecoveryState('idle')
          return
        } catch (error) {
          const serviceUnavailable = isServiceUnavailableError(error)
          lastErrorWasServiceUnavailable.current = serviceUnavailable

          if (attempt < maxAttempts) {
            const attemptDelay = serviceUnavailable
              ? baseDelay * Math.pow(2, attempt - 1)
              : baseDelay
            await delay(attemptDelay)
          }
        }
      }

      if (sequence === requestSequence.current) {
        clearReconnectingTimer()
        if (!lastErrorWasServiceUnavailable.current) {
          setRecoveryState('failed')
        }
      }
    } finally {
      if (mode === 'explicit' && sequence === requestSequence.current) {
        explicitRecoveryActive.current = false
      }
    }
  }, [recoverSession, revalidateSession, clearReconnectingTimer])

  useEffect(() => {
    const handlePageShow = (event: PageTransitionEvent) => {
      if (event.persisted) {
        void runRecovery('automatic')
      }
    }
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        void runRecovery('automatic')
      }
    }

    window.addEventListener('pageshow', handlePageShow)
    document.addEventListener('visibilitychange', handleVisibilityChange)
    return () => {
      requestSequence.current += 1
      explicitRecoveryActive.current = false
      clearReconnectingTimer()
      window.removeEventListener('pageshow', handlePageShow)
      document.removeEventListener('visibilitychange', handleVisibilityChange)
    }
  }, [runRecovery, clearReconnectingTimer])

  return (
    <>
      {children}
      {recoveryState !== 'idle' && (
        <div
          aria-live="assertive"
          className="fixed inset-x-3 top-3 z-[100] mx-auto max-w-md rounded-xl border border-stone-200 bg-white p-4 shadow-lg"
          role={recoveryState === 'failed' ? 'alert' : 'status'}
        >
          {recoveryState === 'reconnecting' ? (
            <p className="text-sm font-medium text-stone-700">Reconnecting ComicPile...</p>
          ) : (
            <>
              <p className="font-semibold text-stone-900">ComicPile could not reconnect</p>
              <p className="mt-1 text-sm text-stone-600">
                Your last screen is still here. Retry the connection or reload the app.
              </p>
              <div className="mt-3 flex gap-2">
                <button
                  className="rounded-lg bg-stone-900 px-3 py-2 text-sm font-medium text-white"
                  onClick={() => void runRecovery('explicit')}
                  type="button"
                >
                  Retry
                </button>
                <button
                  className="rounded-lg border border-stone-300 px-3 py-2 text-sm font-medium text-stone-700"
                  onClick={() => window.location.reload()}
                  type="button"
                >
                  Reload
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </>
  )
}