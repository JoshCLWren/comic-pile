import { useMutation } from '@tanstack/react-query'
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

export function useRate() {
  const mutation = useMutation({
    mutationFn: async (data: RatePayload) => {
      try {
        const result = await protectedRollMutationApi.rate(data)
        await applyRatedThreadCache(queryClient, result)

        try {
          await fetchAndPublishRollBootstrap()
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
              () => protectedRollMutationApi.rate(data),
            )
            if (recovery.status === 'retried') {
              await applyRatedThreadCache(queryClient, recovery.value)
              await fetchAndPublishRollBootstrap()
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
            const committed = await reconcileAmbiguousRollMutation(data.thread_id)
            if (committed) return undefined
          } catch (reconciliationError: unknown) {
            console.error(
              'Failed to reconcile ambiguous rating result:',
              reconciliationError,
            )
          }
        }

        throw error
      }
    },
  })

  return {
    mutate: mutation.mutateAsync,
    isPending: mutation.isPending,
    isError: mutation.isError,
  }
}
