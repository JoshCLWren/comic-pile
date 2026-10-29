import { useRef, useState } from 'react'
import type { CacheEffectsApi, ProtectedRollMutationApi, RollBootstrapApi } from '../services/apiTypes'
import type { RollBootstrapResponse } from '../types/rollBootstrap'
import { applyRatedThreadCache } from '../query/cacheEffects'
import { queryClient } from '../query/queryClient'
import { protectedRollMutationApi } from '../services/protectedRollMutationApi'
import type { RatePayload, RateResult } from '../types'
import {
  fetchAndPublishRollBootstrap,
  isAmbiguousNetworkFailure,
  isAuthenticationMutationFailure,
  reconcileAmbiguousRollMutation,
  recoverProtectedRollMutation,
} from './rollMutationReconciliation'

/**
 * Result of one successful Rate mutation.
 *
 * `bootstrap` is the authoritative Roll state that this mutation already
 * fetched and published, or `null` when that follow-up refresh failed. Callers
 * must use this published snapshot instead of refetching bootstrap: the
 * network request has already happened, and a second one would both duplicate
 * traffic and depend on the zero-delay reconciliation window still being open.
 */
export interface RateMutationOutcome {
  rate: RateResult | undefined
  bootstrap: RollBootstrapResponse | null
}

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
  const inFlightRequest = useRef<Promise<RateMutationOutcome> | null>(null)

  const mutate = async (data: RatePayload): Promise<RateMutationOutcome> => {
    if (inFlightRequest.current) return inFlightRequest.current

    setIsPending(true)
    setIsError(false)

    const request: Promise<RateMutationOutcome> = (async () => {
      try {
        const result = await protectedRollApi.rate(data)
        await applyCache(client, result)

        let bootstrap: RollBootstrapResponse | null = null
        try {
          bootstrap = await fetchAndPublishRollBootstrap(rollBootstrap)
        } catch (reconciliationError: unknown) {
          console.error(
            'Rating saved but authoritative Roll state failed to refresh:',
            reconciliationError,
          )
        }

        return { rate: result, bootstrap }
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
              let bootstrap: RollBootstrapResponse | null = null
              try {
                bootstrap = await fetchAndPublishRollBootstrap(rollBootstrap)
              } catch (reconciliationError: unknown) {
                console.error(
                  'Rating saved but authoritative Roll state failed to refresh:',
                  reconciliationError,
                )
              }
              return { rate: recovery.value, bootstrap }
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
            const reconciliation = await reconcileAmbiguousRollMutation(
              data.thread_id,
              rollBootstrap,
            )
            if (reconciliation.committed) {
              return { rate: undefined, bootstrap: reconciliation.bootstrap }
            }
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
