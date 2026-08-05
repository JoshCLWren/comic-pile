import { useCallback, useRef, useState } from 'react'
import { snoozeApi } from '../services/api'
import { getApiErrorDetail } from '../utils/apiError'
import {
  fetchAndPublishRollBootstrap,
  isAmbiguousNetworkFailure,
  reconcileAmbiguousRollMutation,
} from './rollMutationReconciliation'

type SnoozeResult = Awaited<ReturnType<typeof snoozeApi.snooze>> | undefined

const SNOOZE_REFRESH_ATTEMPTS = 2

export function useSnooze() {
  const [isPending, setIsPending] = useState(false)
  const [isError, setIsError] = useState(false)
  const [refreshError, setRefreshError] = useState<unknown>(null)
  const inFlightRequest = useRef<Promise<SnoozeResult> | null>(null)
  const refreshRequest = useRef<Promise<boolean> | null>(null)

  const refreshAuthoritativeState = useCallback(async (): Promise<boolean> => {
    if (refreshRequest.current) return refreshRequest.current

    const request = (async () => {
      for (let attempt = 1; attempt <= SNOOZE_REFRESH_ATTEMPTS; attempt += 1) {
        try {
          await fetchAndPublishRollBootstrap()
          setRefreshError(null)
          return true
        } catch (error: unknown) {
          if (attempt === SNOOZE_REFRESH_ATTEMPTS) {
            setRefreshError(error)
            console.error(
              'Snooze saved but authoritative Roll state failed to refresh:',
              getApiErrorDetail(error),
            )
            return false
          }
        }
      }
      return false
    })()

    refreshRequest.current = request
    try {
      return await request
    } finally {
      refreshRequest.current = null
    }
  }, [])

  const retryRefresh = useCallback(async (): Promise<boolean> => {
    setIsPending(true)
    try {
      return await refreshAuthoritativeState()
    } finally {
      setIsPending(false)
    }
  }, [refreshAuthoritativeState])

  const mutate = async (expectedPendingThreadId?: number): Promise<SnoozeResult> => {
    if (inFlightRequest.current) return inFlightRequest.current

    setIsPending(true)
    setIsError(false)
    setRefreshError(null)

    const request: Promise<SnoozeResult> = (async () => {
      try {
        const result = await snoozeApi.snooze()
        await refreshAuthoritativeState()
        return result
      } catch (error: unknown) {
        if (isAmbiguousNetworkFailure(error)) {
          try {
            const committed = await reconcileAmbiguousRollMutation(expectedPendingThreadId)
            if (committed) return undefined
          } catch (reconciliationError: unknown) {
            console.error(
              'Failed to reconcile ambiguous snooze result:',
              getApiErrorDetail(reconciliationError),
            )
          }
        }

        setIsError(true)
        console.error('Failed to snooze thread:', getApiErrorDetail(error))
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

  return {
    mutate,
    retryRefresh,
    isPending,
    isError,
    refreshError,
    hasRefreshError: refreshError !== null,
  }
}

export function useUnsnooze() {
  const [isPending, setIsPending] = useState(false)
  const [isError, setIsError] = useState(false)

  const mutate = async (threadId: number) => {
    setIsPending(true)
    setIsError(false)
    try {
      await snoozeApi.unsnooze(threadId)
    } catch (error: unknown) {
      setIsError(true)
      console.error('Failed to unsnooze thread:', getApiErrorDetail(error))
      throw error
    } finally {
      setIsPending(false)
    }
  }

  return { mutate, isPending, isError }
}
