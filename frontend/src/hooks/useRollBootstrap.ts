import { useCallback, useMemo } from 'react'
import { skipToken, useQuery } from '@tanstack/react-query'
import type { RollBootstrapResponse, RollBootstrapThread } from '../types/rollBootstrap'
import type { RateResponsePayload, SessionMode } from '../types'
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
  const snoozedIds = useMemo(() => readRollSnoozes(), [])
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

  // The snooze shelf is the only consumer of these summaries. One bounded page
  // replaces the snoozed section of the retired aggregate; no per-series fetch.
  const snoozedSummaries = useQuery({
    queryKey: queryKeys.roll.snoozedSummaries(),
    queryFn: () => threadsApi.list({ page_size: 200 }),
    enabled: snoozedIds.length > 0,
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

    const activeThread: RollBootstrapThread | null = pending
      ? rollPool.find((thread) => thread.issue_id === pending.issue_id) ?? {
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
        tags: thread.tags ?? [],
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
    isError: die.isError || eligible.isError || cards.isError || dependencyQuery.isError,
    error: die.error ?? eligible.error ?? cards.error ?? dependencyQuery.error ?? null,
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
