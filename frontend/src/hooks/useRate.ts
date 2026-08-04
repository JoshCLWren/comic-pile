import { useRef, useState } from 'react'
import { rateApi } from '../services/api'
import { getApiErrorDetail } from '../utils/apiError'
import type { RatePayload } from '../types'
import {
  fetchAndPublishRollBootstrap,
  isAmbiguousNetworkFailure,
  reconcileAmbiguousRollMutation,
} from './rollMutationReconciliation'

type RateResult = Awaited<ReturnType<typeof rateApi.rate>> | undefined

export function useRate() {
  const [isPending, setIsPending] = useState(false)
  const [isError, setIsError] = useState(false)
  const inFlightRequest = useRef<Promise<RateResult> | null>(null)

  const mutate = async (data: RatePayload): Promise<RateResult> => {
    if (inFlightRequest.current) return inFlightRequest.current

    setIsPending(true)
    setIsError(false)

    const request: Promise<RateResult> = (async () => {
      try {
        const result = await rateApi.rate(data)

        try {
          await fetchAndPublishRollBootstrap()
        } catch (reconciliationError: unknown) {
          console.error(
            'Rating saved but authoritative Roll state failed to refresh:',
            getApiErrorDetail(reconciliationError),
          )
        }

        return result
      } catch (error: unknown) {
        if (isAmbiguousNetworkFailure(error)) {
          try {
            const committed = await reconcileAmbiguousRollMutation(data.thread_id)
            if (committed) return undefined
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
