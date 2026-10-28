import { useCallback, useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import type { RollBootstrapResponse } from '../types/rollBootstrap'
import type { RollBootstrapApi } from '../services/apiTypes'
import { rollBootstrapApi } from '../services/rollBootstrapApi'
import { useToast } from '../contexts/useToast'
import { trackSessionGreeting } from '../utils/sessionGreeting'
import { queryClient } from '../query/queryClient'
import { queryKeys } from '../query/queryKeys'
import { ROLL_BOOTSTRAP_RECONCILED_EVENT } from './rollMutationReconciliation'

/** Best-effort browser IANA timezone used to timestamp the reading session. */
export function resolveBrowserTimezone(): string | undefined {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || undefined
  } catch {
    return undefined
  }
}

export function useRollBootstrap(api?: RollBootstrapApi) {
  const bootstrapApi = api ?? rollBootstrapApi
  const { showToast } = useToast()
  const justReconciledRef = useRef<RollBootstrapResponse | null>(null)
  const reconciliationExpiryRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  // Bumped on every fetch and on every reconciliation so a stale in-flight
  // request can be identified and ignored once a newer fetch or a reconciliation
  // has superseded it (mirrors the pre-React-Query generation guard).
  const requestGenerationRef = useRef(0)

  const { data, isPending, isError, error, failureCount, isSuccess, refetch } = useQuery({
    queryKey: queryKeys.roll.bootstrap(),
    queryFn: async (): Promise<RollBootstrapResponse | null> => {
      const generation = ++requestGenerationRef.current
      try {
        const result = await bootstrapApi.get(resolveBrowserTimezone())
        // A reconciliation (or newer fetch) superseded this request before it
        // settled. Keep the authoritative cache instead of applying stale data.
        if (generation !== requestGenerationRef.current) {
          return queryClient.getQueryData<RollBootstrapResponse | null>(
            queryKeys.roll.bootstrap(),
          ) ?? null
        }

        // Normalize v2 bootstrap response to the legacy RollBootstrapResponse
        // shape expected by downstream consumers. v2 provides `rollable` items with
        // nested thread/issue structures; convert them to the flat
        // RollBootstrapThread shape with top-level id/title/format.
        const raw = result as any
        // If the response already has roll_pool (legacy v1 shape), return it as-is
        // to preserve reference equality for tests and avoid unnecessary mapping.
        if (Array.isArray(raw.roll_pool) && !Array.isArray(raw.rollable)) {
          return raw as RollBootstrapResponse
        }

        const convertThread = (t: any) => ({
          id: t?.id,
          title: t?.title ?? '',
          format: t?.format ?? '',
          last_activity_at: t?.last_activity_at ?? null,
        })
        const roll_pool = Array.isArray(raw.rollable)
          ? raw.rollable.map((item: any) => ({
              id: item?.thread?.id,
              title: item?.thread?.title ?? '',
              format: item?.thread?.format ?? '',
              issue_id: item?.issue?.id ?? null,
              issue_number: item?.issue?.number ?? null,
              last_activity_at: item?.thread?.last_activity_at ?? null,
            }))
          : []

        const normalized: RollBootstrapResponse = {
          session_id: raw.session_id,
          user_id: raw.user_id,
          current_die: raw.current_die,
          manual_die: raw.manual_die,
          pending_thread_id: raw.pending_thread_id,
          last_rolled_result: raw.last_rolled_result,
          session_mode: raw.session_mode,
          active_thread: raw.active_thread,
          roll_recovery: raw.roll_recovery,
          roll_pool,
          snoozed_threads: Array.isArray(raw.snoozed_threads) ? raw.snoozed_threads.map(convertThread) : [],
          snoozed_count: raw.snoozed_count ?? 0,
          skipped_thread_ids: raw.skipped_thread_ids ?? [],
          skipped_threads: Array.isArray(raw.skipped_threads) ? raw.skipped_threads.map(convertThread) : [],
          blocked_count: raw.blocked_count ?? 0,
          blocked_threads: Array.isArray(raw.blocked_threads) ? raw.blocked_threads.map(convertThread) : [],
          stale_thread_count: raw.stale_thread_count ?? 0,
          stale_thread: raw.stale_thread ? convertThread(raw.stale_thread) : null,
          timezone: raw.timezone ?? null,
        }

        return normalized
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

  // React Query resets `failureCount` to 0 on every fetch, including the retry
  // a user starts from the Retry affordance. Keying the bounded loading state
  // on `failureCount` alone therefore drops RollPage back to the bare loading
  // splash the instant someone presses Retry, which is the frozen-splash symptom
  // issue #3429 exists to remove. Latch the first failure instead so the
  // affordance survives user-initiated retries until the load actually succeeds.
  const [hasFailedLoad, setHasFailedLoad] = useState(false)
  useEffect(() => {
    if (failureCount > 0) {
      setHasFailedLoad(true)
    } else if (isSuccess) {
      setHasFailedLoad(false)
    }
  }, [failureCount, isSuccess])

  // Persist the active reading session and greet on a genuinely new session.
  // Previously lived inside the manual fetch; now runs whenever authoritative
  // bootstrap data changes (initial load or reconciliation). Greeting
  // persistence and the session-started toast are owned by the shared
  // `sessionGreeting` helper so the current-session query and this bootstrap
  // can never race on the same storage key or double-toast.
  useEffect(() => {
    if (data == null) return

    trackSessionGreeting({ sessionId: data.session_id, userId: data.user_id, showToast })
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
      // SAFETY: the helper only dispatches this event name with a RollBootstrapResponse detail payload.
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
    // SAFETY: the bootstrap queryFn normalizes failures to Error, so the query error value is Error | null.
    error: (error as Error | null) ?? null,
    // Number of failed attempts so far. The shared retry policy keeps a
    // timed-out bootstrap in pending through several retries (issue #3429).
    failureCount,
    // True while the initial load is still trying after at least one failure,
    // including the retries a user starts from the Retry affordance. Keyed on
    // isPending (already observed) rather than isFetching so the retry
    // affordance never adds a new render subscription of its own.
    isRetrying: isPending && hasFailedLoad,
    refetch: refetchBootstrap,
  }
}
