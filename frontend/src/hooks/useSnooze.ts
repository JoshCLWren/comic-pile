import { useCallback, useRef, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { invalidateCurrentSessionAfterSnooze } from '../query/cacheEffects'
import { queryClient } from '../query/queryClient'
import { snoozeApi } from '../services/api'
import { protectedRollMutationApi } from '../services/protectedRollMutationApi'
import {
  fetchAndPublishRollBootstrap,
  isAmbiguousNetworkFailure,
  isAuthenticationMutationFailure,
  reconcileAmbiguousRollMutation,
  recoverProtectedRollMutation,
} from './rollMutationReconciliation'

const SNOOZE_REFRESH_ATTEMPTS = 2

export function useSnooze() {
  const [refreshError, setRefreshError] = useState<unknown>(null)
  const inFlightRequest = useRef<Promise<unknown> | null>(null)
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
    return refreshAuthoritativeState()
  }, [refreshAuthoritativeState])

  const mutation = useMutation({
    mutationFn: async (expectedPendingThreadId?: number) => {
      if (inFlightRequest.current) return inFlightRequest.current
      if (refreshRequest.current) {
        await refreshRequest.current
        return undefined
      }

      const request: Promise<unknown> = (async () => {
        try {
          const result = await protectedRollMutationApi.snooze()
          await invalidateCurrentSessionAfterSnooze(queryClient)
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
                () => protectedRollMutationApi.snooze(),
              )
              if (recovery.status === 'retried') {
                await invalidateCurrentSessionAfterSnooze(queryClient)
                await refreshAuthoritativeState()
                return recovery.value
              }
            } catch (recoveryError: unknown) {
              console.error(
                'Failed to recover snooze after authentication expiry:',
                recoveryError,
              )
            }
          }

          if (isAmbiguousNetworkFailure(error)) {
            try {
              const committed = await reconcileAmbiguousRollMutation(expectedPendingThreadId)
              if (committed) return undefined
            } catch (reconciliationError: unknown) {
              console.error(
                'Failed to reconcile ambiguous snooze result:',
                reconciliationError,
              )
            }
          }

          throw error
        }
      })()

      inFlightRequest.current = request

      try {
        return await request
      } finally {
        inFlightRequest.current = null
      }
    },
  })

  return {
    mutate: mutation.mutateAsync,
    retryRefresh,
    isPending: mutation.isPending,
    isError: mutation.isError,
    refreshError,
    hasRefreshError: refreshError !== null,
  }
}

export function useUnsnooze() {
  const mutation = useMutation({
    mutationFn: (threadId: number) => snoozeApi.unsnooze(threadId),
    onSuccess: async () => {
      await invalidateCurrentSessionAfterSnooze(queryClient)
    },
  })

  return {
    mutate: mutation.mutateAsync,
    isPending: mutation.isPending,
    isError: mutation.isError,
  }
}
