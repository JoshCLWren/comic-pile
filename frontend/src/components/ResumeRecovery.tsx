import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { queryClient } from '../query/queryClient'

const RESUME_REQUEST_TIMEOUT_MS = 15000
const MAX_RESUME_ATTEMPTS = 6
const RESUME_RETRY_DELAYS_MS = [1000, 2000, 4000, 8000, 16000]

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

function isServerUnavailable(error: unknown): boolean {
  const status = (error as { response?: { status?: number } })?.response?.status
  return status === 503
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

    if (mode === 'explicit') {
      setRecoveryState('reconnecting')
    }

    const recover = mode === 'explicit' ? recoverSession : revalidateSession

    try {
      let lastError: unknown = null
      for (let attempt = 1; attempt <= MAX_RESUME_ATTEMPTS; attempt += 1) {
        try {
          await recover(RESUME_REQUEST_TIMEOUT_MS)
          if (sequence !== requestSequence.current) {
            return
          }
          await queryClient.invalidateQueries()
          if (sequence !== requestSequence.current) {
            return
          }
          setRecoveryState('idle')
          return
        } catch (error) {
          lastError = error
          if (sequence !== requestSequence.current) {
            return
          }
          if (attempt < MAX_RESUME_ATTEMPTS) {
            const backoffIndex = Math.min(attempt - 1, RESUME_RETRY_DELAYS_MS.length - 1)
            await delay(RESUME_RETRY_DELAYS_MS[backoffIndex])
          }
        }
      }

      if (sequence === requestSequence.current) {
        const isTransient = isServerUnavailable(lastError)
        if (mode === 'automatic' && isTransient) {
          await recover(RESUME_REQUEST_TIMEOUT_MS).catch(() => {})
          if (sequence === requestSequence.current) {
            await queryClient.invalidateQueries().catch(() => {})
            setRecoveryState('idle')
          }
          return
        }
        setRecoveryState('failed')
      }
    } finally {
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
      {recoveryState === 'reconnecting' && (
        <div
          aria-live="polite"
          className="fixed bottom-4 right-4 z-[100] flex items-center gap-2 rounded-full border border-stone-200 bg-white/90 px-3 py-1.5 text-xs text-stone-500 shadow-sm backdrop-blur-sm"
          role="status"
        >
          <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-stone-400" />
          Reconnecting…
        </div>
      )}
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
    </>
  )
}
