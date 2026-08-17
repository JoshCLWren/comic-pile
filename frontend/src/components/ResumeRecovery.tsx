import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import axios from 'axios'
import { queryClient } from '../query/queryClient'

export const RESUME_REQUEST_TIMEOUT_MS = 15000
export const RESUME_INITIAL_RETRY_DELAY_MS = 800
export const RESUME_MAX_BACKOFF_MS = 5000
export const RESUME_MAX_ATTEMPTS = 4

// A quick reconnect (for example a serverless function warming back up) should be
// completely invisible to the user. Only surface the reconnecting indicator after this
// grace period has elapsed, so the common cold-start case never looks like an error.
export const RESUME_RECONNECTING_GRACE_MS = 1200

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

function retryDelayForAttempt(attempt: number): number {
  return Math.min(
    RESUME_INITIAL_RETRY_DELAY_MS * 2 ** (attempt - 1),
    RESUME_MAX_BACKOFF_MS,
  )
}

// Transient failures (network drops and 5xx / 429 server hiccups such as a serverless
// cold start) should be retried patiently. Definitive authentication rejections (401)
// mean the session is genuinely gone and must surface an error instead of spinning.
function isTransientResumeError(error: unknown): boolean {
  if (!axios.isAxiosError(error) || !error.response) {
    return true
  }
  const status = error.response.status
  if (status === 401) {
    return false
  }
  return status >= 500 || status === 429
}

export default function ResumeRecovery({
  children,
  revalidateSession,
  recoverSession,
}: ResumeRecoveryProps) {
  const [recoveryState, setRecoveryState] = useState<RecoveryState>('idle')
  const [isReconnectingVisible, setIsReconnectingVisible] = useState(false)
  const requestSequence = useRef(0)
  const lastValidationAt = useRef(0)
  const explicitRecoveryActive = useRef(false)

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
    setRecoveryState('reconnecting')
    // An explicit retry is user-initiated, so show feedback immediately; an automatic
    // reconnect stays hidden until the grace period passes.
    setIsReconnectingVisible(mode === 'explicit')

    let graceTimer: number | undefined
    if (mode === 'automatic') {
      graceTimer = window.setTimeout(() => {
        if (sequence === requestSequence.current) {
          setIsReconnectingVisible(true)
        }
      }, RESUME_RECONNECTING_GRACE_MS)
    }

    const clearReconnectingUi = () => {
      if (graceTimer !== undefined) {
        window.clearTimeout(graceTimer)
      }
      setIsReconnectingVisible(false)
    }

    const recover = mode === 'explicit' ? recoverSession : revalidateSession

    try {
      let attempt = 0
      while (true) {
        attempt += 1
        try {
          await recover(RESUME_REQUEST_TIMEOUT_MS)
          if (sequence !== requestSequence.current) {
            return
          }
          await queryClient.invalidateQueries()
          if (sequence !== requestSequence.current) {
            return
          }
          clearReconnectingUi()
          setRecoveryState('idle')
          return
        } catch (error) {
          if (sequence !== requestSequence.current) {
            return
          }
          const transient = isTransientResumeError(error)
          if (!transient) {
            console.error(`ComicPile resume validation failed (attempt ${attempt})`, error)
            clearReconnectingUi()
            setRecoveryState('failed')
            return
          }
          console.warn(`ComicPile reconnecting after transient error (attempt ${attempt})`, error)
          if (attempt >= RESUME_MAX_ATTEMPTS) {
            clearReconnectingUi()
            setRecoveryState('failed')
            return
          }
          await delay(retryDelayForAttempt(attempt))
        }
      }
    } finally {
      clearReconnectingUi()
      if (mode === 'explicit' && sequence === requestSequence.current) {
        explicitRecoveryActive.current = false
      }
    }
  }, [recoverSession, revalidateSession])

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
      window.removeEventListener('pageshow', handlePageShow)
      document.removeEventListener('visibilitychange', handleVisibilityChange)
    }
  }, [runRecovery])

  return (
    <>
      {children}
      {recoveryState === 'failed' && (
        <div
          aria-live="assertive"
          className="fixed inset-x-3 top-3 z-[100] mx-auto max-w-md rounded-xl border border-stone-200 bg-white p-4 shadow-lg"
          role="alert"
        >
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
        </div>
      )}
      {recoveryState === 'reconnecting' && isReconnectingVisible && (
        <div
          aria-live="polite"
          className="fixed inset-x-3 top-3 z-[100] mx-auto max-w-md rounded-xl border border-stone-200 bg-white p-4 shadow-lg"
          role="status"
        >
          <p className="text-sm font-medium text-stone-700">Reconnecting ComicPile...</p>
        </div>
      )}
    </>
  )
}
