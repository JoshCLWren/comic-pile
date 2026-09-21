import { useCallback, useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import type { RollMutationDeps } from '../services/apiTypes'
import { invalidateCurrentSessionAfterSnooze } from '../query/cacheEffects'
import { skipApi } from '../services/api'
import { protectedRollMutationApi } from '../services/protectedRollMutationApi'
import {
  fetchAndPublishRollBootstrap,
  isAmbiguousNetworkFailure,
  isAuthenticationMutationFailure,
  reconcileAmbiguousRollMutation,
  recoverProtectedRollMutation,
} from './rollMutationReconciliation'

type SkipResult = Awaited<ReturnType<typeof protectedRollMutationApi.skip>> | undefined

const SKIP_REFRESH_ATTEMPTS = 2

export function useSkip(deps: RollMutationDeps = {}) {
  const { protectedApi, bootstrapApi, cacheEffects } = deps
  const protectedRollApi = protectedApi ?? protectedRollMutationApi
  const rollBootstrap = bootstrapApi
  const invalidateSessionCache = cacheEffects?.invalidateCurrentSessionAfterSnooze ?? invalidateCurrentSessionAfterSnooze
  const queryClient = useQueryClient()
  const [isPending, setIsPending] = useState(false)
  const [isError, setIsError] = useState(false)
  const [refreshError, setRefreshError] = useState<unknown>(null)
  const inFlightRequest = useRef<Promise<SkipResult> | null>(null)
  const refreshRequest = useRef<Promise<boolean> | null>(null)

  const refreshAuthoritativeState = useCallback(async (): Promise<boolean> => {
    if (refreshRequest.current) return refreshRequest.current

    const request = (async () => {
      let result = false
      for (let attempt = 1; attempt <= SKIP_REFRESH_ATTEMPTS; attempt += 1) {
        try {
          await fetchAndPublishRollBootstrap(rollBootstrap)
          setRefreshError(null)
          result = true
          return result
        } catch (error: unknown) {
          if (attempt === SKIP_REFRESH_ATTEMPTS) {
            setRefreshError(error)
            result = false
          }
        }
      }
      return result
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
      return await refreshAuthoritativeState()
    } finally {
      setIsPending(false)
    }
  }, [refreshAuthoritativeState])

  const mutate = async (expectedPendingThreadId?: number): Promise<SkipResult> => {
    if (inFlightRequest.current) return inFlightRequest.current
    if (refreshRequest.current) {
      await refreshRequest.current
      return undefined
    }

    setIsPending(true)
    setIsError(false)
    setRefreshError(null)

    const request: Promise<SkipResult> = (async () => {
      try {
        const result = await protectedRollApi.skip()
        await invalidateSessionCache(queryClient)
        await refreshAuthoritativeState()
        return result
      } catch (error: unknown) {
        if (
          expectedPendingThreadId !== undefined
          && isAuthenticationMutationFailure(error)
        ) {
          try {
            const recovery = await recoverProtectedRollMutation(
              expectedPendingThreadId,
              () => protectedRollApi.skip(),
              undefined,
              protectedRollApi,
            )
            if (recovery.status === 'retried') {
              await invalidateSessionCache(queryClient)
              await refreshAuthoritativeState()
              return recovery.value
            }
          } catch (_recoveryError: unknown) {
            // Recovery failure exposed via isError / refreshError.
          }
        }

        if (isAmbiguousNetworkFailure(error)) {
          try {
            const committed = await reconcileAmbiguousRollMutation(
              expectedPendingThreadId,
              rollBootstrap,
            )
            if (committed) return undefined
          } catch (_reconciliationError: unknown) {
            // Reconciliation failure exposed via isError / refreshError.
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

export function useUnskip(deps: RollMutationDeps = {}) {
  const skip = deps.skipApi ?? skipApi
  const invalidateSessionCache = deps.cacheEffects?.invalidateCurrentSessionAfterSnooze ?? invalidateCurrentSessionAfterSnooze
  const queryClient = useQueryClient()
  const mutation = useMutation({
    mutationFn: (threadId: number) => skip.unskip(threadId),
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
