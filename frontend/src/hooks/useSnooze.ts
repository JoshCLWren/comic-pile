import { useRef, useState } from 'react'
import { snoozeApi } from '../services/api'
import { getApiErrorDetail } from '../utils/apiError'
import {
  fetchAndPublishRollBootstrap,
  isAmbiguousNetworkFailure,
  reconcileAmbiguousRollMutation,
} from './rollMutationReconciliation'

type SnoozeResult = Awaited<ReturnType<typeof snoozeApi.snooze>> | undefined

export function useSnooze() {
  const [isPending, setIsPending] = useState(false)
  const [isError, setIsError] = useState(false)
  const inFlightRequest = useRef<Promise<SnoozeResult> | null>(null)

  const mutate = async (expectedPendingThreadId?: number): Promise<SnoozeResult> => {
    if (inFlightRequest.current) return inFlightRequest.current

    setIsPending(true)
    setIsError(false)

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

  return { mutate, isPending, isError }
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
