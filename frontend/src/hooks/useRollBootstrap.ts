import { useCallback, useEffect, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import type { RollBootstrapResponse } from '../types/rollBootstrap'
import { rollBootstrapApi } from '../services/rollBootstrapApi'
import { useToast } from '../contexts/useToast'
import { ROLL_BOOTSTRAP_RECONCILED_EVENT } from './rollMutationReconciliation'
import { queryKeys } from '../query/queryKeys'

const STORAGE_KEY_PREFIX = 'comic_pile_last_session_id'

export function useRollBootstrap() {
  const { showToast } = useToast()
  const lastNotifiedSessionIdRef = useRef<number | null>(null)
  const justReconciledRef = useRef<RollBootstrapResponse | null>(null)
  const reconciliationExpiryRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const query = useQuery({
    queryKey: queryKeys.roll.bootstrap(),
    queryFn: async () => {
      const result = await rollBootstrapApi.get()

      const currentSessionId = result.session_id
      const currentUserId = result.user_id ?? 'anonymous'
      const storageKey = `${STORAGE_KEY_PREFIX}_${currentUserId}`
      let storedSessionId: string | null = null
      try {
        storedSessionId = localStorage.getItem(storageKey)
      } catch {
        // Session loading should still succeed when browser storage is unavailable.
      }
      let previousSessionId: number | null = null
      if (storedSessionId) {
        const parsed = parseInt(storedSessionId, 10)
        previousSessionId = Number.isFinite(parsed) ? parsed : null
      }

      if (
        previousSessionId !== null &&
        currentSessionId !== previousSessionId &&
        currentSessionId !== lastNotifiedSessionIdRef.current
      ) {
        showToast('Session started. Happy reading!', 'info')
        lastNotifiedSessionIdRef.current = currentSessionId
      }

      try {
        localStorage.setItem(storageKey, currentSessionId.toString())
      } catch {
        // Persisting the session ID is best effort and must not hide the API result.
      }

      return result
    },
    staleTime: 30_000,
    retry: false,
  })

  const refetchBootstrap = useCallback(async () => {
    const reconciled = justReconciledRef.current
    if (reconciled) {
      justReconciledRef.current = null
      if (reconciliationExpiryRef.current) {
        clearTimeout(reconciliationExpiryRef.current)
        reconciliationExpiryRef.current = null
      }
      return reconciled
    }

    return query.refetch()
  }, [query])

  useEffect(() => {
    const handleReconciledBootstrap = (event: Event) => {
      const reconciled = (event as CustomEvent<RollBootstrapResponse>).detail
      if (!reconciled) return

      justReconciledRef.current = reconciled
      if (reconciliationExpiryRef.current) clearTimeout(reconciliationExpiryRef.current)
      reconciliationExpiryRef.current = setTimeout(() => {
        if (justReconciledRef.current === reconciled) justReconciledRef.current = null
        reconciliationExpiryRef.current = null
      }, 0)

      // Update the query cache directly
      query.client.setQueryData(queryKeys.roll.bootstrap(), reconciled)
    }

    window.addEventListener(ROLL_BOOTSTRAP_RECONCILED_EVENT, handleReconciledBootstrap)
    return () => {
      window.removeEventListener(ROLL_BOOTSTRAP_RECONCILED_EVENT, handleReconciledBootstrap)
      if (reconciliationExpiryRef.current) clearTimeout(reconciliationExpiryRef.current)
    }
  }, [query.client])

  return {
    data: query.data ?? null,
    isPending: query.isLoading,
    isError: query.isError,
    error: query.error ?? null,
    refetch: refetchBootstrap,
  }
}
