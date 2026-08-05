import { useRef, useState } from 'react'
import { snoozeApi } from '../services/api'
import { getApiErrorDetail } from '../utils/apiError'
import {
  fetchAndPublishRollBootstrap,
  isAmbiguousNetworkFailure,
  reconcileAmbiguousRollMutation,
  publishRollBootstrap,
} from './rollMutationReconciliation'

type SnoozeResult = Awaited<ReturnType<typeof snoozeApi.snooze>> | undefined

export function useSnooze() {
  const [isPending, setIsPending] = useState(false)
  const [isError, setIsError] = useState(false)
  const [refreshError, setRefreshError] = useState<unknown>(null)
  const [refreshRetryCount, setRefreshRetryCount] = useState(0)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const inFlightRequest = useRef<Promise<SnoozeResult> | null>(null)

  const mutate = async (expectedPendingThreadId?: number): Promise<SnoozeResult> => {
    if (inFlightRequest.current) return inFlightRequest.current

    setIsPending(true)
    setIsError(false)
    setRefreshError(null)
    setRefreshRetryCount(0)

    const request: Promise<SnoozeResult> = (async () => {
      try {
        const result = await snoozeApi.snooze()

        try {
          await fetchAndPublishRollBootstrap()
        } catch (reconciliationError: unknown) {
          console.error(
            'Snooze saved but authoritative Roll state failed to refresh:',
            getApiErrorDetail(reconciliationError),
          )
          setRefreshError(reconciliationError)
        }

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

  const retryRefresh = async (): Promise<void> => {
    if (isRefreshing) return

    setIsRefreshing(true)
    setRefreshError(null)

    try {
      const state = await fetchAndPublishRollBootstrap()
      publishRollBootstrap(state)
      setRefreshRetryCount(0)
    } catch (error: unknown) {
      console.error(
        'Failed to refresh Roll state after retry:',
        getApiErrorDetail(error),
      )
      const newRetryCount = refreshRetryCount + 1
      setRefreshRetryCount(newRetryCount)
      setRefreshError(error)
    } finally {
      setIsRefreshing(false)
    }
  }

  const clearRefreshError = (): void => {
    setRefreshError(null)
  }

  return { mutate, retryRefresh, clearRefreshError, isPending, isError, refreshError, isRefreshing, refreshRetryCount }
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

export function useSnoozeRefresh() {
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [refreshError, setRefreshError] = useState<unknown>(null)

  const refresh = async (): Promise<void> => {
    setIsRefreshing(true)
    setRefreshError(null)

    try {
      const state = await fetchAndPublishRollBootstrap()
      publishRollBootstrap(state)
    } catch (error: unknown) {
      console.error(
        'Failed to refresh Roll state:',
        getApiErrorDetail(error),
      )
      setRefreshError(error)
    } finally {
      setIsRefreshing(false)
    }
  }

  const clearError = (): void => {
    setRefreshError(null)
  }

  return { refresh, isRefreshing, refreshError, clearError }
}
