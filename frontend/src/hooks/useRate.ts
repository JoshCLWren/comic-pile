import { useRef, useState } from 'react'
import type { CacheEffectsApi, ProtectedRollMutationApi, RollBootstrapApi } from '../services/apiTypes'
import { applyRatedThreadCache } from '../query/cacheEffects'
import { queryClient } from '../query/queryClient'
import { protectedRollMutationApi } from '../services/protectedRollMutationApi'
import type { RatePayload } from '../types'
import {
  fetchAndPublishRollBootstrap,
  isAmbiguousNetworkFailure,
  isAuthenticationMutationFailure,
  reconcileAmbiguousRollMutation,
  recoverProtectedRollMutation,
} from './rollMutationReconciliation'

type RateResult = Awaited<ReturnType<typeof protectedRollMutationApi.rate>> | undefined

export interface RateDeps {
  protectedApi?: ProtectedRollMutationApi
  bootstrapApi?: RollBootstrapApi
  cacheEffects?: CacheEffectsApi
  queryClientInstance?: typeof queryClient
}

export function useRate(deps: RateDeps = {}) {
  const { protectedApi, bootstrapApi, cacheEffects, queryClientInstance } = deps
  const protectedRollApi = protectedApi ?? protectedRollMutationApi
  const rollBootstrap = bootstrapApi
  const applyCache = cacheEffects?.applyRatedThreadCache ?? applyRatedThreadCache
  const client = queryClientInstance ?? queryClient
  const [isPending, setIsPending] = useState(false)
  const [isError, setIsError] = useState(false)
  const inFlightRequest = useRef<Promise<RateResult> | null>(null)

  const mutate = async (data: RatePayload): Promise<RateResult> => {
    if (inFlightRequest.current) return inFlightRequest.current

    setIsPending(true)
    setIsError(false)

    const request: Promise<RateResult> = (async () => {
      try {
        const result = await protectedRollApi.rate(data)
        await applyCache(client, result)

        try {
          await fetchAndPublishRollBootstrap(rollBootstrap)
        } catch (reconciliationError: unknown) {
          console.error(
            'Rating saved but authoritative Roll state failed to refresh:',
            reconciliationError,
          )
        }

        return result
      } catch (error: unknown) {
        if (isAuthenticationMutationFailure(error)) {
          try {
            const recovery = await recoverProtectedRollMutation(
              data.thread_id,
              () => protectedRollApi.rate(data),
              undefined,
              protectedRollApi,
            )
            if (recovery.status === 'retried') {
              await applyCache(client, recovery.value)
              await fetchAndPublishRollBootstrap(rollBootstrap)
              return recovery.value
            }
          } catch (recoveryError: unknown) {
            console.error(
              'Failed to recover rating after authentication expiry:',
              recoveryError,
            )
          }
        }

        if (isAmbiguousNetworkFailure(error)) {
          try {
            const committed = await reconcileAmbiguousRollMutation(
              data.thread_id,
              rollBootstrap,
            )
            if (committed) return undefined
          } catch (reconciliationError: unknown) {
            console.error(
              'Failed to reconcile ambiguous rating result:',
              reconciliationError,
            )
          }
        }

        setIsError(true)
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
