import { useCallback, useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { invalidateCurrentSessionAfterSnooze } from '../query/cacheEffects'
import { skipApi } from '../services/api'
import { protectedRollMutationApi } from '../services/protectedRollMutationApi'
import { getApiErrorDetail } from '../utils/apiError'
import {
  fetchAndPublishRollBootstrap,
  isAmbiguousNetworkFailure,
  isAuthenticationMutationFailure,
  reconcileAmbiguousRollMutation,
  recoverProtectedRollMutation,
} from './rollMutationReconciliation'

type SkipResult = Awaited<ReturnType<typeof protectedRollMutationApi.skip>> | undefined

const SKIP_REFRESH_ATTEMPTS = 2

export function useSkip() {
  const queryClient = useQueryClient()
  const [isPending, setIsPending] = useState(false)
  const [isError, setIsError] = useState(false)
  const [refreshError, setRefreshError] = useState<unknown>(null)
  const inFlightRequest = useRef<Promise<SkipResult> | null>(null)
  const refreshRequest = useRef<Promise<boolean> | null>(null)

  const refreshAuthoritativeState = useCallback(async (): Promise<boolean> => {
    if (refreshRequest.current) return refreshRequest.current

    const request = (async () => {
      for (let attempt = 1; attempt <= SKIP_REFRESH_ATTEMPTS; attempt += 1) {
        try {
          await fetchAndPublishRollBootstrap()
          setRefreshError(null)
          return true
        } catch (error: unknown) {
          if (attempt === SKIP_REFRESH_ATTEMPTS) {
            setRefreshError(error)
            console.error(
              'Skip saved but authoritative Roll state failed to refresh:',
              getApiErrorDetail(error),
            )
            return false
          }
        }
      }
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
        const result = await protectedRollMutationApi.skip()
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
              () => protectedRollMutationApi.skip(),
            )
            if (recovery.status === 'retried') {
              await invalidateCurrentSessionAfterSnooze(queryClient)
              await refreshAuthoritativeState()
              return recovery.value
            }
          } catch (recoveryError: unknown) {
            console.error(
              'Failed to recover skip after authentication expiry:',
              getApiErrorDetail(recoveryError),
            )
          }
        }

        if (isAmbiguousNetworkFailure(error)) {
          try {
            const committed = await reconcileAmbiguousRollMutation(expectedPendingThreadId)
            if (committed) return undefined
          } catch (reconciliationError: unknown) {
            console.error(
              'Failed to reconcile ambiguous skip result:',
              getApiErrorDetail(reconciliationError),
            )
          }
        }

        setIsError(true)
        console.error('Failed to skip thread:', getApiErrorDetail(error))
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

export function useUnskip() {
  const queryClient = useQueryClient()
  const mutation = useMutation({
    mutationFn: (threadId: number) => skipApi.unskip(threadId),
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
