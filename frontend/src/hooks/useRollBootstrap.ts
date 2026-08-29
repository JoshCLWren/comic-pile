import { useCallback, useEffect, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import type { RollBootstrapResponse } from '../types/rollBootstrap'
import { rollBootstrapApi } from '../services/rollBootstrapApi'
import { useToast } from '../contexts/useToast'
import { queryClient } from '../query/queryClient'
import { queryKeys } from '../query/queryKeys'
import { ROLL_BOOTSTRAP_RECONCILED_EVENT } from './rollMutationReconciliation'

const STORAGE_KEY_PREFIX = 'comic_pile_last_session_id'

/** Best-effort browser IANA timezone used to timestamp the reading session. */
export function resolveBrowserTimezone(): string | undefined {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || undefined
  } catch {
    return undefined
  }
}


export function useRollBootstrap() {
  const { showToast } = useToast()
  const lastNotifiedSessionIdRef = useRef<number | null>(null)
  const justReconciledRef = useRef<RollBootstrapResponse | null>(null)
  const reconciliationExpiryRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: queryKeys.roll.bootstrap(),
    queryFn: () => rollBootstrapApi.get(resolveBrowserTimezone()),
    staleTime: Infinity,
    gcTime: Infinity,
    refetchOnWindowFocus: false,
    retry: false,
  })

  useEffect(() => {
    if (!data) return
    const currentSessionId = data.session_id
    const currentUserId = data.user_id ?? 'anonymous'
    const storageKey = `${STORAGE_KEY_PREFIX}_${currentUserId}`
    let storedSessionId: string | null = null
    try {
      storedSessionId = localStorage.getItem(storageKey)
    } catch {
      // ignore
    }
    let previousSessionId: number | null = null
    if (storedSessionId) {
      const parsed = parseInt(storedSessionId, 10)
      previousSessionId = Number.isFinite(parsed) ? parsed : null
    }

    if (
      previousSessionId !== null
      && currentSessionId !== previousSessionId
      && currentSessionId !== lastNotifiedSessionIdRef.current
    ) {
      showToast('Session started. Happy reading!', 'info')
      lastNotifiedSessionIdRef.current = currentSessionId
    }

    try {
      localStorage.setItem(storageKey, currentSessionId.toString())
    } catch {
      // best effort
    }
  }, [data, showToast])

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

      queryClient.setQueryData(queryKeys.roll.bootstrap(), reconciled)
    }

    window.addEventListener(ROLL_BOOTSTRAP_RECONCILED_EVENT, handleReconciledBootstrap)
    return () => {
      window.removeEventListener(ROLL_BOOTSTRAP_RECONCILED_EVENT, handleReconciledBootstrap)
      if (reconciliationExpiryRef.current) clearTimeout(reconciliationExpiryRef.current)
    }
  }, [])

  const refetchBootstrap = useCallback(async (): Promise<RollBootstrapResponse | undefined> => {
    const reconciled = justReconciledRef.current
    if (reconciled) {
      justReconciledRef.current = null
      if (reconciliationExpiryRef.current) {
        clearTimeout(reconciliationExpiryRef.current)
        reconciliationExpiryRef.current = null
      }
      return reconciled
    }

    const result = await refetch()
    return result.data ?? undefined
  }, [refetch])

  return { data: data ?? null, isPending, isError, error, refetch: refetchBootstrap }
}
