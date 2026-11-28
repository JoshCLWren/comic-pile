import { useCallback, useMemo } from 'react'
import { skipToken, useQuery } from '@tanstack/react-query'
import type { RollBootstrapResponse, RollBootstrapThread } from '../types/rollBootstrap'
import type { RateResponsePayload, SessionMode, SessionThread } from '../types'
import type { ReadingGraphResponse } from '../generated/nativeV2Client'
import { queryClient } from '../query/queryClient'
import { queryKeys } from '../query/queryKeys'
import { readRollSnoozes } from '../services/api-roll'
import { threadsApi } from '../services/api-threads'
import { dependenciesApi } from '../services/api-dependencies'
import { buildRollRecovery } from '../services/rollRecovery'
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

export interface UseRollBootstrapResult {
  data: RollBootstrapResponse | null
  isPending: boolean
  isError: boolean
  error: unknown
  failureCount: number
  isRetrying: boolean
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
  const { pending } = useRollPendingSelection()
  const die = useRollDieState()
  // Read the cookie on every render: a committed snooze/unsnooze changes it
  // without remounting the Roll page, and the composed pool/chips must follow
  // the same browser-owned source as the page's scoped face queries.
  const snoozedIds = readRollSnoozes()
  const eligible = useRollEligibleIssueIds(snoozedIds)
  const issueIds = useMemo(() => eligible.data?.issue_ids ?? [], [eligible.data])
  const threadIds = useMemo(() => eligible.data?.thread_ids ?? [], [eligible.data])
  const cards = useRollIssueCards(issueIds)

  // A pending issue missing from the eligible pool may be continuity-blocked.
  // Only then is one bounded, owner-scoped issue-edge GET needed; a cold idle
  // Roll load issues no extra request.
  const blockedIssueId = pending != null && !issueIds.includes(pending.issue_id)
    ? pending.issue_id
    : null
  // A restored exact selection may have been removed from the eligible pool by
  // the offer that created it. Its card is no longer in the visible batch, so
  // the owning thread summary is the bounded source for the rating metadata the
  // hydration path needs after a reload.
  const pendingThreadId = pending?.thread_id ?? null
  const needsPendingThread = blockedIssueId != null && pendingThreadId != null
  const dependencyQuery = useQuery({
    queryKey: queryKeys.dependencies.issueEdges(blockedIssueId ?? -1),
    queryFn: () => dependenciesApi.getIssueDependencies(blockedIssueId ?? 0),
    enabled: blockedIssueId != null,
  })
  const prerequisiteIds = useMemo(
    () => [...new Set((dependencyQuery.data?.incoming ?? []).map((edge) => edge.source_issue_id))],
    [dependencyQuery.data],
  )
  const prerequisiteCards = useRollIssueCards(prerequisiteIds)

  // One bounded page feeds the snooze shelf and supplies metadata for a blocked
  // pending issue; there is no per-series fetch and no request on a cold idle load.
  const snoozedSummaries = useQuery({
    queryKey: queryKeys.roll.snoozedSummaries(),
    queryFn: () => threadsApi.list({ page_size: 200 }),
    enabled: snoozedIds.length > 0 || needsPendingThread,
    staleTime: 60_000,
  })

  // Both queries are cache-only: the rate mutation and ReadingGraphProblemCard
  // already own the live fetches on this page.
  const rateQuery = useQuery<RateResponsePayload | null>({
    queryKey: queryKeys.roll.lastRead(),
    queryFn: skipToken,
  })
  const graphQuery = useQuery<ReadingGraphResponse | null>({
    queryKey: queryKeys.readingGraph.status(),
    queryFn: skipToken,
  })

  const composed = useMemo<RollBootstrapResponse>(() => {
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

    const pendingThreadSummary = needsPendingThread
      ? snoozedSummaries.data?.threads.find((candidate) => candidate.id === pendingThreadId)
      : undefined
    const activeThread: SessionThread | null = pending
      ? pendingThreadSummary
        ? {
            id: pendingThreadSummary.id,
            title: pendingThreadSummary.title,
            format: pendingThreadSummary.format,
            issues_remaining: pendingThreadSummary.issues_remaining,
            queue_position: pendingThreadSummary.queue_position,
            total_issues: pendingThreadSummary.total_issues ?? null,
            issue_id: pending.issue_id,
            issue_number: pending.issue_number ?? null,
            last_rolled_result: pending.result ?? null,
          }
        : rollPool.find((thread) => thread.issue_id === pending.issue_id) ?? {
            id: pending.thread_id,
            title: '',
            format: '',
            issue_id: pending.issue_id,
            issue_number: pending.issue_number ?? null,
          }
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

    const recovery = pending != null
      ? buildRollRecovery({
          pending,
          eligibleIssueIds: issueIds,
          dependencies: blockedIssueId != null ? dependencyQuery.data ?? null : null,
          prerequisiteCards: prerequisiteCards.data?.items ?? [],
          graph: graphQuery.data ?? null,
          originalTitle: activeThread?.title || null,
        })
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
      // Seeded by the committed rate response, never invented here (#2720).
      last_read: rateQuery.data?.roll_reconciliation?.last_read ?? null,
    }
  }, [
    cards.data,
    pending,
    snoozedIds,
    issueIds,
    threadIds,
    blockedIssueId,
    needsPendingThread,
    pendingThreadId,
    dependencyQuery.data,
    prerequisiteCards.data,
    graphQuery.data,
    rateQuery.data,
    snoozedSummaries.data,
    eligible.data?.pool_reason,
  ])

  // Callers still handle a null view while the scoped queries settle.
  const data: RollBootstrapResponse | null = composed
  const isPending = die.isPending
    || eligible.isPending
    || (composed.roll_pool.length > 0 && cards.isPending)
    || (blockedIssueId != null && dependencyQuery.isPending)
    || (needsPendingThread && snoozedSummaries.isPending)

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
    return queryClient.getQueryData<RollBootstrapResponse>(queryKeys.roll.bootstrap()) ?? composed
  }, [die, eligible, cards, composed])

  return {
    data,
    isPending,
    isError: die.isError || eligible.isError || cards.isError || dependencyQuery.isError
      || (needsPendingThread && snoozedSummaries.isError),
    error: die.error ?? eligible.error ?? cards.error ?? dependencyQuery.error
      ?? (needsPendingThread ? snoozedSummaries.error : null) ?? null,
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
