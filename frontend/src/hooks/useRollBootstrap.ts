import { useCallback, useMemo } from 'react'
import type { RollBootstrapResponse, RollBootstrapThread } from '../types/rollBootstrap'
import type { SessionMode } from '../types'
import { queryClient } from '../query/queryClient'
import { queryKeys } from '../query/queryKeys'
import { readRollSnoozes } from '../services/api-roll'
import { useRollDieState, useRollEligibleIssueIds, useRollIssueCards } from './useRollResources'
import { useRollPendingSelection } from './useRollPendingSelection'
import { ROLL_BOOTSTRAP_RECONCILED_EVENT } from './rollMutationReconciliation'

/** Best-effort browser IANA timezone, retained for callers that display it. */
export function resolveBrowserTimezone(): string | undefined {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || undefined
  } catch {
    return undefined
  }
}

const EMPTY_SESSION_MODE: SessionMode = {
  active_bandwidth: null,
  predicted_bandwidth: null,
  bandwidth_confidence: null,
  bandwidth_source: null,
  bandwidth_version: null,
  active_intent: null,
  predicted_intent: null,
  intent_confidence: null,
  intent_source: null,
  intent_version: null,
  session_mode_correction_guidance: null,
}

/**
 * Read-only Roll view model assembled entirely from scoped native resources.
 *
 * There is no aggregate server request and no session initialization here: the
 * die, ordered eligible pool, visible cards and browser-owned pending selection
 * are the same inputs the Roll surface already consumes. The returned shape is
 * retained as the page's local view model so feature modules share one snapshot;
 * it is never sent to, or fetched from, a bootstrap/session endpoint.
 */
export function useRollBootstrap(_api?: unknown) {
  // The optional transport argument is retained for existing focused tests;
  // scoped state comes from the shared query cache, never from that transport.
  void _api
  const { pending } = useRollPendingSelection()
  const die = useRollDieState()
  const snoozedIds = useMemo(() => readRollSnoozes(), [])
  const eligible = useRollEligibleIssueIds(snoozedIds)
  const cards = useRollIssueCards(eligible.data?.issue_ids ?? [])

  const data: RollBootstrapResponse | null = useMemo<RollBootstrapResponse>(() => {
    const issueIds = eligible.data?.issue_ids ?? []
    const threadIds = eligible.data?.thread_ids ?? []
    const cardByIssue = new Map((cards.data?.items ?? []).map((card) => [card.issue_id, card]))
    const rollPool: RollBootstrapThread[] = issueIds.flatMap((issueId, index) => {
      const card = cardByIssue.get(issueId)
      if (!card) return []
      return [{
        id: card.thread_id ?? threadIds[index] ?? 0,
        title: card.thread_title,
        format: '',
        issue_id: card.issue_id,
        issue_number: card.display_issue_number ?? card.issue_number,
        tags: [],
        route_labels: [],
        overflow_routes_count: 0,
      }]
    })

    const activeThread: RollBootstrapThread | null = pending
      ? rollPool.find((thread) => thread.issue_id === pending.issue_id) ?? {
          id: pending.thread_id,
          title: '',
          format: '',
          issue_id: pending.issue_id,
          issue_number: pending.issue_number ?? null,
        }
      : null

    return {
      session_id: 0,
      user_id: 0,
      pending_thread_id: pending?.thread_id ?? null,
      last_rolled_result: pending?.result ?? null,
      session_mode: EMPTY_SESSION_MODE,
      active_thread: activeThread,
      roll_recovery: null,
      roll_pool: rollPool,
      snoozed_threads: [],
      snoozed_count: snoozedIds.length,
      snoozed_thread_ids: snoozedIds,
      skipped_thread_ids: [],
      skipped_threads: [],
      pool_reason: eligible.data?.pool_reason ?? 'ready',
    }
  }, [eligible.data, cards.data, pending, snoozedIds])

  const isPending = die.isPending || eligible.isPending || (data.roll_pool.length > 0 && cards.isPending)

  const refetch = useCallback(async (): Promise<RollBootstrapResponse> => {
    // A reconciled mutation publishes its already-fetched scoped snapshot on
    // this event; consume it instead of issuing another request.
    const reconciled = queryClient.getQueryData<RollBootstrapResponse>(queryKeys.roll.bootstrap())
    if (reconciled) return reconciled
    await Promise.all([
      die.refetch(),
      eligible.refetch(),
      cards.refetch(),
    ])
    return queryClient.getQueryData<RollBootstrapResponse>(queryKeys.roll.bootstrap()) ?? data
  }, [die, eligible, cards, data])

  return {
    data: data as RollBootstrapResponse | null,
    isPending,
    isError: die.isError || eligible.isError || cards.isError,
    error: die.error ?? eligible.error ?? cards.error ?? null,
    failureCount: 0,
    isRetrying: false,
    refetch,
  }
}

/**
 * Publish a reconciled scoped snapshot. Kept as a named export so the mutation
 * reconciliation event has one owner and never performs a network fetch.
 */
export function publishScopedRollSnapshot(snapshot: RollBootstrapResponse): void {
  queryClient.setQueryData(queryKeys.roll.bootstrap(), snapshot)
  if (typeof window === 'undefined') return
  window.dispatchEvent(new CustomEvent<RollBootstrapResponse>(
    ROLL_BOOTSTRAP_RECONCILED_EVENT,
    { detail: snapshot },
  ))
}
