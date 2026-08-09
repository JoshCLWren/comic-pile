import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { queryClient } from '../query/queryClient'

const RESUME_REQUEST_TIMEOUT_MS = 15000
const RESUME_RETRY_DELAY_MS = 750
const MAX_RESUME_ATTEMPTS = 2

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
    setRecoveryState('reconnecting')
    const recover = mode === 'explicit' ? recoverSession : revalidateSession

    try {
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
          console.error(`ComicPile resume validation failed (attempt ${attempt})`, error)
          if (attempt < MAX_RESUME_ATTEMPTS) {
            await delay(RESUME_RETRY_DELAY_MS)
          }
        }
      }

      if (sequence === requestSequence.current) {
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
