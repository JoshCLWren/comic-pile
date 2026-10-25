import { useCallback, useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import type { CacheEffectsApi, ProtectedRollMutationApi, RollBootstrapApi, RollMutationDeps, SnoozeApi } from '../services/apiTypes'
import { invalidateCurrentSessionAfterSnooze } from '../query/cacheEffects'
import { snoozeApi } from '../services/api-snooze'
import { protectedRollMutationApi } from '../services/protectedRollMutationApi'
import {
  fetchAndPublishRollBootstrap,
  isAmbiguousNetworkFailure,
  isAuthenticationMutationFailure,
  reconcileAmbiguousRollMutation,
  recoverProtectedRollMutation,
} from './rollMutationReconciliation'

type SnoozeResult = Awaited<ReturnType<typeof protectedRollMutationApi.snooze>> | undefined

/**
 * Result of one committed Snooze submission.
 *
 * The mutation owns the single authoritative bootstrap refresh, so callers must
 * read the refresh outcome from this value instead of the hook's render state:
 * a `hasRefreshError` field captured in the caller's closure is the value from
 * the render *before* the mutation settled and cannot report a failure that the
 * mutation just recorded.
 */
export interface SnoozeMutationOutcome {
  /** Backend response for a committed snooze; undefined when the call reconciled without one. */
  response: SnoozeResult
  /** True when the post-mutation authoritative bootstrap refresh published fresh state. */
  refreshed: boolean
  /** Failure from the exhausted refresh attempts, when `refreshed` is false. */
  refreshError: unknown
}

interface RefreshOutcome {
  refreshed: boolean
  error: unknown
}

const SNOOZE_REFRESH_ATTEMPTS = 2

export function useSnooze(deps: RollMutationDeps = {}) {
  const { protectedApi, bootstrapApi, cacheEffects } = deps
  const protectedRollApi = protectedApi ?? protectedRollMutationApi
  const rollBootstrap = bootstrapApi
  const invalidateSessionCache = cacheEffects?.invalidateCurrentSessionAfterSnooze ?? invalidateCurrentSessionAfterSnooze
  const queryClient = useQueryClient()
  const [isPending, setIsPending] = useState(false)
  const [isError, setIsError] = useState(false)
  const [refreshError, setRefreshError] = useState<unknown>(null)
  const inFlightRequest = useRef<Promise<SnoozeMutationOutcome> | null>(null)
  const refreshRequest = useRef<Promise<RefreshOutcome> | null>(null)

  const refreshAuthoritativeState = useCallback(async (): Promise<RefreshOutcome> => {
    if (refreshRequest.current) return refreshRequest.current

    const request = (async (): Promise<RefreshOutcome> => {
      for (let attempt = 1; attempt <= SNOOZE_REFRESH_ATTEMPTS; attempt += 1) {
        try {
          await fetchAndPublishRollBootstrap(rollBootstrap)
          setRefreshError(null)
          return { refreshed: true, error: null }
        } catch (error: unknown) {
          if (attempt === SNOOZE_REFRESH_ATTEMPTS) {
            setRefreshError(error)
            return { refreshed: false, error }
          }
        }
      }
      return { refreshed: false, error: null }
    })()

    refreshRequest.current = request
    try {
      return await request
    } finally {
      refreshRequest.current = null
    }
  }, [rollBootstrap])

  const retryRefresh = useCallback(async (): Promise<boolean> => {
    setIsPending(true)
    try {
      const outcome = await refreshAuthoritativeState()
      return outcome.refreshed
    } finally {
      setIsPending(false)
    }
  }, [refreshAuthoritativeState])

  const mutate = async (expectedPendingThreadId?: number): Promise<SnoozeMutationOutcome> => {
    if (inFlightRequest.current) return inFlightRequest.current
    if (refreshRequest.current) {
      const outcome = await refreshRequest.current
      return { response: undefined, refreshed: outcome.refreshed, refreshError: outcome.error }
    }

    setIsPending(true)
    setIsError(false)
    setRefreshError(null)

    const request: Promise<SnoozeMutationOutcome> = (async () => {
      try {
        const result = await protectedRollApi.snooze()
        await invalidateSessionCache(queryClient)
        const refresh = await refreshAuthoritativeState()
        return { response: result, refreshed: refresh.refreshed, refreshError: refresh.error }
      } catch (error: unknown) {
        if (
          expectedPendingThreadId !== undefined
          && isAuthenticationMutationFailure(error)
        ) {
          try {
            const recovery = await recoverProtectedRollMutation(
              expectedPendingThreadId,
              () => protectedRollApi.snooze(),
              undefined,
              protectedRollApi,
            )
            if (recovery.status === 'retried') {
              await invalidateSessionCache(queryClient)
              const refresh = await refreshAuthoritativeState()
              return {
                response: recovery.value,
                refreshed: refresh.refreshed,
                refreshError: refresh.error,
              }
            }
          } catch (_recoveryError: unknown) {
            // Recovery failure is exposed via isError / refreshError; no console fallback.
          }
        }

        if (isAmbiguousNetworkFailure(error)) {
          try {
            const { committed } = await reconcileAmbiguousRollMutation(
              expectedPendingThreadId,
              rollBootstrap,
            )
            if (committed) {
              // The reconciliation already fetched and published authoritative
              // bootstrap state, so no further refresh is needed here.
              return { response: undefined, refreshed: true, refreshError: null }
            }
          } catch (_reconciliationError: unknown) {
            // Reconciliation failure is exposed via isError / refreshError.
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

  return {
    mutate,
    retryRefresh,
    isPending,
    isError,
    refreshError,
    hasRefreshError: refreshError !== null,
  }
}

export function useUnsnooze(deps: RollMutationDeps = {}) {
  const snooze = deps.snoozeApi ?? snoozeApi
  const invalidateSessionCache = deps.cacheEffects?.invalidateCurrentSessionAfterSnooze ?? invalidateCurrentSessionAfterSnooze
  const queryClient = useQueryClient()
  const mutation = useMutation({
    mutationFn: (threadId: number) => snooze.unsnooze(threadId),
    onSuccess: async () => {
      await invalidateSessionCache(queryClient)
    },
  })

  return {
    mutate: mutation.mutateAsync,
    isPending: mutation.isPending,
    isError: mutation.isError,
  }
}
