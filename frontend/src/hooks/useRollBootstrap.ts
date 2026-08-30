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
  // Bumped on every fetch and on every reconciliation so a stale in-flight
  // request can be identified and ignored once a newer fetch or a reconciliation
  // has superseded it (mirrors the pre-React-Query generation guard).
  const requestGenerationRef = useRef(0)

  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: queryKeys.roll.bootstrap(),
    queryFn: async (): Promise<RollBootstrapResponse | null> => {
      const generation = ++requestGenerationRef.current
      try {
        const result = await rollBootstrapApi.get(resolveBrowserTimezone())
        // A reconciliation (or newer fetch) superseded this request before it
        // settled. Keep the authoritative cache instead of applying stale data.
        if (generation !== requestGenerationRef.current) {
          return queryClient.getQueryData<RollBootstrapResponse | null>(
            queryKeys.roll.bootstrap(),
          ) ?? null
        }
        return result
      } catch (err) {
        const normalized =
          err instanceof Error ? err : new Error('Failed to fetch roll bootstrap')
        if (generation !== requestGenerationRef.current) {
          // Stale failure: leave the authoritative cache untouched.
          return (
            queryClient.getQueryData<RollBootstrapResponse | null>(
              queryKeys.roll.bootstrap(),
            ) ?? null
          )
        }
        throw normalized
      }
    },
  })

  // Persist the active reading session and greet on a genuinely new session.
  // Previously lived inside the manual fetch; now runs whenever authoritative
  // bootstrap data changes (initial load or reconciliation).
  useEffect(() => {
    if (data == null) return

    const currentSessionId = data.session_id
    const currentUserId = data.user_id ?? 'anonymous'
    const storageKey = `${STORAGE_KEY_PREFIX}_${currentUserId}`

    let previousSessionId: number | null = null
    try {
      const storedSessionId = localStorage.getItem(storageKey)
      if (storedSessionId) {
        const parsed = parseInt(storedSessionId, 10)
        previousSessionId = Number.isFinite(parsed) ? parsed : null
      }
    } catch {
      // Session loading should still succeed when browser storage is unavailable.
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
  }, [data, showToast])

  const refetchBootstrap = useCallback(async (): Promise<RollBootstrapResponse> => {
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
    if (result.isError) throw result.error ?? new Error('Failed to fetch roll bootstrap')
    // The refetch result carries the settled data even though the query observer
    // re-renders asynchronously, so return it directly instead of re-reading the
    // cache (which can still hold the pre-refetch value at this microtask boundary).
    const fresh = result.data
    if (fresh == null) throw new Error('Failed to fetch roll bootstrap')
    return fresh
  }, [refetch])

  useEffect(() => {
    const handleReconciledBootstrap = (event: Event) => {
      const reconciled = (event as CustomEvent<RollBootstrapResponse>).detail
      if (!reconciled) return

      requestGenerationRef.current += 1
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

  return {
    data: data ?? null,
    isPending,
    isError,
    error: (error as Error | null) ?? null,
    refetch: refetchBootstrap,
  }
}
