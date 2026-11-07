import { useRef, useState } from 'react'
import type { CacheEffectsApi, ProtectedRollMutationApi, RollBootstrapApi } from '../services/apiTypes'
import type { RollBootstrapResponse } from '../types/rollBootstrap'
import { applyRatedThreadCache } from '../query/cacheEffects'
import { queryClient } from '../query/queryClient'
import { protectedRollMutationApi } from '../services/protectedRollMutationApi'
import type { RatePayload, RateResponsePayload } from '../types'
import {
  fetchAndPublishRollBootstrap,
  isAmbiguousNetworkFailure,
  isAuthenticationMutationFailure,
  reconcileAmbiguousRollMutation,
  recoverProtectedRollMutation,
} from './rollMutationReconciliation'
import { addRollSnooze } from '../services/api-roll'
import { RATING_THRESHOLD } from '../pages/RollPage/utils'

/**
 * Whether a committed Roll-offer rating should temporarily snooze its thread
 * so the next roll does not offer it again (#4699).
 *
 * A below-threshold rating steps the die up and seats the series beyond the
 * die-sized pool, but that seating cannot keep a comic out of the pool when
 * the eligible set is smaller than the die itself (the pool then covers the
 * whole library). The browser-owned temporary snooze is the mechanism that
 * removes the comic from the next pool in that case, and it is also applied
 * when the seating already placed it beyond the pool. A finished series
 * leaves the pool through completion, and manual (`direct`) ratings never
 * carry Roll's queue semantics, so neither snoozes.
 */
function shouldSnoozeAfterRating(
  data: RatePayload,
  issuesRemaining: number | undefined,
): boolean {
  if (data.source !== 'roll_offer') return false
  if (!(data.rating < RATING_THRESHOLD)) return false
  // A finished series leaves the pool through completion, so it needs no
  // snooze. When the remaining count is unavailable (a reconciled ambiguous
  // rating), snooze: the thread was just offered and is presumed still in
  // play, and the entry expires at midnight.
  if (issuesRemaining !== undefined && issuesRemaining <= 0) return false
  return true
}

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
  rate: RateResponsePayload | undefined
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

        // Write the temporary snooze before refetching bootstrap so the
        // published pool already excludes the just-rated below-threshold
        // comic (#4699).
        if (shouldSnoozeAfterRating(data, result?.issues_remaining)) {
          addRollSnooze(data.thread_id)
        }

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
              if (shouldSnoozeAfterRating(data, recovery.value?.issues_remaining)) {
                addRollSnooze(data.thread_id)
              }
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
              if (shouldSnoozeAfterRating(data, undefined)) {
                // The reconciling bootstrap was fetched before the snooze was
                // recorded; refetch so the published pool excludes the comic.
                addRollSnooze(data.thread_id)
                const bootstrap = await fetchAndPublishRollBootstrap(rollBootstrap)
                return { rate: undefined, bootstrap }
              }
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
