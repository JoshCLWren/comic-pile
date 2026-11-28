import { useCallback, useEffect, useMemo } from 'react'
import { skipToken, useQuery } from '@tanstack/react-query'
import type { RollBootstrapResponse, RollBootstrapThread } from '../types/rollBootstrap'
import type { RateResponsePayload, SessionMode } from '../types'
import { queryClient } from '../query/queryClient'
import { queryKeys } from '../query/queryKeys'
import { readRollSnoozes } from '../services/api-roll'
import { threadsApi } from '../services/api-threads'
import { rollResourcesApi } from '../services/rollResourcesApi'
import { parseRollRecovery } from '../services/rollRecovery'
import {
  useRollDieState,
  useRollEligibleIssueIds,
  useRollIssueCards,
  useRollLastReadRecord,
} from './useRollResources'
import { useRollPendingSelection } from './useRollPendingSelection'
import { publishRollBootstrap } from './rollMutationReconciliation'

/** Best-effort browser IANA timezone, retained for callers that display it. */
export function resolveBrowserTimezone(): string | undefined {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || undefined
  } catch {
    return undefined
  }
}

export interface UseRollBootstrapResult {
  data: RollBootstrapResponse | null
  isPending: boolean
  isError: boolean
  error: unknown
  failureCount: number
  isRetrying: boolean
  /** Optional blocked-selection diagnostics load independently of the Roll pool. */
  recoveryIsPending: boolean
  recoveryError: unknown
  refetch: () => Promise<RollBootstrapResponse>
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
 * die, ordered eligible pool, visible cards, browser-owned pending selection,
 * scoped last-read cache and owner-scoped recovery diagnostics are the same
 * inputs the Roll surface already consumes. The returned shape is retained as
 * the page's local view model so feature modules share one snapshot; it is
 * never sent to, or fetched from, a bootstrap/session endpoint.
 */
export function useRollBootstrap(): UseRollBootstrapResult {
  const { pending: storedPending, clear: clearPending } = useRollPendingSelection()
  const die = useRollDieState()
  // Read the cookie on every render: a committed snooze/unsnooze changes it
  // without remounting the Roll page, and the composed pool/chips must follow
  // the same browser-owned source as the page's scoped face queries.
  const snoozedIds = readRollSnoozes()
  const eligible = useRollEligibleIssueIds(snoozedIds)
  const issueIds = useMemo(() => eligible.data?.issue_ids ?? [], [eligible.data])
  const threadIds = useMemo(() => eligible.data?.thread_ids ?? [], [eligible.data])
  const cards = useRollIssueCards(issueIds)
  const pendingCardIds = useMemo(
    () => storedPending != null && !issueIds.includes(storedPending.issue_id)
      ? [storedPending.issue_id]
      : [],
    [storedPending, issueIds],
  )
  const pendingCards = useRollIssueCards(pendingCardIds)
  const pendingCard = storedPending != null
    ? cards.data?.items.find((card) => card.issue_id === storedPending.issue_id)
      ?? pendingCards.data?.items.find((card) => card.issue_id === storedPending.issue_id)
    : undefined
  const pending = storedPending != null && pendingCard != null && pendingCard.status !== 'read'
    ? storedPending
    : null

  const pendingCardReady = pendingCardIds.length > 0 ? pendingCards.isSuccess : cards.isSuccess
  useEffect(() => {
    if (storedPending == null || !pendingCardReady) return
    if (pendingCard == null || pendingCard.status === 'read') clearPending(storedPending.issue_id)
  }, [storedPending, pendingCardReady, pendingCard, clearPending])

  // A pending issue missing from the eligible pool may be continuity-blocked.
  // Only then does the canonical bounded recovery resource run; a cold idle
  // Roll load issues no extra request.
  const blockedIssueId = pending != null && !issueIds.includes(pending.issue_id)
    ? pending.issue_id
    : null
  const recoveryQuery = useQuery({
    queryKey: queryKeys.roll.recovery(blockedIssueId ?? -1, snoozedIds),
    queryFn: () => rollResourcesApi.recovery(blockedIssueId ?? 0, snoozedIds),
    enabled: blockedIssueId != null,
  })

  // The snooze shelf is the only consumer of these summaries. One bounded page
  // replaces the snoozed section of the retired aggregate; no per-series fetch.
  const snoozedSummaries = useQuery({
    queryKey: queryKeys.roll.snoozedSummaries(snoozedIds),
    queryFn: () => threadsApi.list({
      ids: snoozedIds.join(','),
      page_size: snoozedIds.length,
    }),
    enabled: snoozedIds.length > 0,
    staleTime: 60_000,
  })

  // The rate cache supplements the scoped durable last-read record.
  const lastReadRecord = useRollLastReadRecord()
  const rateQuery = useQuery<RateResponsePayload | null>({
    queryKey: queryKeys.roll.lastRead(),
    queryFn: skipToken,
  })
  const reconciled = useQuery<RollBootstrapResponse | null>({
    queryKey: queryKeys.roll.bootstrap(),
    queryFn: skipToken,
  })

  const composed = useMemo<RollBootstrapResponse>(() => {
    const cardByIssue = new Map([
      ...(cards.data?.items ?? []),
      ...(pendingCards.data?.items ?? []),
    ].map((card) => [card.issue_id, card]))
    const rollPool: RollBootstrapThread[] = issueIds.flatMap((issueId, index) => {
      const card = cardByIssue.get(issueId)
      if (!card) return []
      return [{
        id: card.thread_id ?? threadIds[index] ?? 0,
        title: card.thread_title,
        format: card.thread_format ?? '',
        issue_id: card.issue_id,
        issue_number: card.display_issue_number ?? card.issue_number,
        tags: card.tags ?? [],
        route_labels: card.route_labels?.slice(0, 3) ?? [],
        overflow_routes_count: card.overflow_routes_count ?? 0,
      }]
    })

    const activeThread: RollBootstrapThread | null = pending
      ? rollPool.find((thread) => thread.issue_id === pending.issue_id) ?? (() => {
          const card = cardByIssue.get(pending.issue_id)
          return card ? {
            id: card.thread_id,
            title: card.thread_title,
            format: card.thread_format ?? '',
            issue_id: card.issue_id,
            issue_number: card.display_issue_number ?? card.issue_number,
            tags: card.tags ?? [],
            route_labels: card.route_labels?.slice(0, 3) ?? [],
            overflow_routes_count: card.overflow_routes_count ?? 0,
          } : null
        })()
      : null

    const snoozedThreads: RollBootstrapThread[] = snoozedIds.flatMap((id) => {
      const thread = snoozedSummaries.data?.threads.find((candidate) => candidate.id === id)
      if (!thread) return []
      return [{
        id: thread.id,
        title: thread.title,
        format: thread.format,
      }]
    })

    const recovery = blockedIssueId != null && recoveryQuery.data != null
      ? parseRollRecovery(recoveryQuery.data)
      : null

    return {
      pending_thread_id: pending?.thread_id ?? null,
      last_rolled_result: pending?.result ?? null,
      session_mode: EMPTY_SESSION_MODE,
      active_thread: activeThread,
      roll_recovery: recovery,
      roll_pool: rollPool,
      snoozed_threads: snoozedThreads,
      snoozed_count: snoozedIds.length,
      snoozed_thread_ids: snoozedIds,
      skipped_thread_ids: [],
      skipped_threads: [],
      pool_reason: eligible.data?.pool_reason ?? 'ready',
      last_read: lastReadRecord.data ?? rateQuery.data?.roll_reconciliation?.last_read ?? null,
    }
  }, [
    cards.data,
    pendingCards.data,
    pending,
    snoozedIds,
    issueIds,
    threadIds,
    blockedIssueId,
    recoveryQuery.data,
    lastReadRecord.data,
    rateQuery.data,
    snoozedSummaries.data,
    eligible.data?.pool_reason,
  ])

  // Callers still handle a null view while the scoped queries settle.
  const data: RollBootstrapResponse | null = reconciled.data ?? composed
  const isPending = die.isPending
    || eligible.isPending
    || lastReadRecord.isPending
    || (issueIds.length > 0 && cards.isPending)
    || (pendingCardIds.length > 0 && pendingCards.isPending)
  const recoveryIsPending = reconciled.data == null
    && blockedIssueId != null
    && recoveryQuery.isPending
  const recoveryError = blockedIssueId != null ? recoveryQuery.error ?? null : null

  const refetch = useCallback(async (): Promise<RollBootstrapResponse> => {
    // A reconciled mutation publishes its already-fetched scoped snapshot on
    // this event; consume it instead of issuing another request.
    const reconciled = queryClient.getQueryData<RollBootstrapResponse>(queryKeys.roll.bootstrap())
    if (reconciled) return reconciled
    await Promise.all([
      die.refetch(),
      eligible.refetch(),
      lastReadRecord.refetch(),
      // `refetch` ignores `enabled`; the cards route rejects an empty batch.
      ...(issueIds.length > 0 ? [cards.refetch()] : []),
      ...(pendingCardIds.length > 0 ? [pendingCards.refetch()] : []),
      ...(blockedIssueId != null ? [recoveryQuery.refetch()] : []),
      ...(snoozedIds.length > 0 ? [snoozedSummaries.refetch()] : []),
    ])
    return queryClient.getQueryData<RollBootstrapResponse>(queryKeys.roll.bootstrap()) ?? composed
  }, [
    die,
    eligible,
    cards,
    issueIds.length,
    pendingCardIds.length,
    pendingCards,
    blockedIssueId,
    recoveryQuery,
    lastReadRecord,
    snoozedIds.length,
    snoozedSummaries,
    composed,
  ])

  return {
    data,
    isPending,
    isError: die.isError || eligible.isError || lastReadRecord.isError
      || cards.isError || pendingCards.isError,
    error: die.error ?? eligible.error ?? lastReadRecord.error
      ?? cards.error ?? pendingCards.error ?? null,
    failureCount: 0,
    isRetrying: false,
    recoveryIsPending,
    recoveryError,
    refetch,
  }
}

/**
 * Publish a reconciled scoped snapshot. Kept as a named export so the mutation
 * reconciliation event has one owner and never performs a network fetch.
 */
export function publishScopedRollSnapshot(snapshot: RollBootstrapResponse): void {
  publishRollBootstrap(snapshot)
}
