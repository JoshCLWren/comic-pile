import { useRef, useState } from 'react'
import { rateApi } from '../services/api'
import { rollBootstrapApi } from '../services/rollBootstrapApi'
import { getApiErrorDetail } from '../utils/apiError'
import type { RatePayload } from '../types'

function isAmbiguousNetworkFailure(error: unknown): boolean {
  if (!error || typeof error !== 'object') return false

  const candidate = error as { code?: string; message?: string; response?: unknown }
  if (candidate.response) return false

  return candidate.code === 'ECONNABORTED'
    || candidate.code === 'ETIMEDOUT'
    || candidate.message?.toLowerCase().includes('timeout') === true
    || candidate.message === 'Network Error'
}

export function useRate() {
  const [isPending, setIsPending] = useState(false)
  const [isError, setIsError] = useState(false)
  const inFlightRequest = useRef<Promise<unknown> | null>(null)

  const mutate = async (data: RatePayload) => {
    if (inFlightRequest.current) return inFlightRequest.current

    setIsPending(true)
    setIsError(false)

    const request = (async () => {
      try {
        return await rateApi.rate(data)
      } catch (error: unknown) {
        if (isAmbiguousNetworkFailure(error)) {
          try {
            const authoritativeState = await rollBootstrapApi.get()
            const pendingThreadId = authoritativeState.pending_thread_id === null
              || authoritativeState.pending_thread_id === undefined
              ? null
              : Number(authoritativeState.pending_thread_id)

            if (pendingThreadId !== data.thread_id) {
              // The write may have committed even though the client timed out.
              // Reloading is intentionally conservative: it replaces every stale
              // rating, queue, and die snapshot with the authoritative bootstrap.
              globalThis.location.reload()
              return undefined
            }
          } catch (reconciliationError: unknown) {
            console.error(
              'Failed to reconcile ambiguous rating result:',
              getApiErrorDetail(reconciliationError),
            )
          }
        }

        setIsError(true)
        console.error('Failed to rate thread:', getApiErrorDetail(error))
        throw error
      }
    })()

    inFlightRequest.current = request

    try {
      return await request
    } finally {
      inFlightRequest.current = null
      setIsPending(false)
    }
  }

  return { mutate, isPending, isError }
}
