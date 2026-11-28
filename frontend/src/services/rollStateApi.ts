import {
  createNativeV2Client,
  type IssueCardsResponse,
  type RollRecovery,
} from '../generated/nativeV2Client'
import { defaultHttpClient, type HttpClient } from './httpClient'
import { readRollSnoozes } from './api-roll'
import { readPendingSelection } from './rollPendingSelection'
import { parseRollRecovery } from './rollRecovery'
import { queryClient } from '../query/queryClient'
import { queryKeys } from '../query/queryKeys'
import type { RateResponsePayload } from '../types'
import type { RollPendingUserId } from './apiTypes'
import type {
  RollState,
  RollThreadSummary,
  RollPrerequisiteSwitchRequest,
} from '../types/rollState'

/**
 * Client-side composition of the scoped Roll resources.
 *
 * Retired aggregate and session-init requests are gone: this service reads only
 * `GET /v2/roll/die-state`, `GET /v2/roll/eligible-issue-ids`,
 * `POST /v2/issues/cards`, one bounded issue-edge GET when a pending issue is
 * blocked, and the browser-owned pending selection. It is kept as a service
 * seam so mutation reconciliation and its tests can ask for the current view
 * without reaching into React hooks.
 */
export function createRollStateApi(client: HttpClient) {
  const nativeV2 = createNativeV2Client(client)

  return {
    get: async (userId?: RollPendingUserId): Promise<RollState> => {
      const [eligible, snoozes, lastRead] = await Promise.all([
        nativeV2.eligibleIssueIds({
          query: readRollSnoozes().length > 0
            ? { snoozed: readRollSnoozes().join(',') }
            : {},
        }),
        Promise.resolve(readRollSnoozes()),
        nativeV2.lastRead(),
      ])
      const issueIds = eligible.issue_ids
      const cards = issueIds.length > 0
        ? await nativeV2.issueCards({ body: { issue_ids: issueIds } })
        : { items: [] }
      const cardByIssue = new Map(cards.items.map((card) => [card.issue_id, card]))
      const rollPool: RollThreadSummary[] = issueIds.flatMap((issueId, index) => {
        const card = cardByIssue.get(issueId)
        if (!card) return []
        return [{
          id: card.thread_id ?? eligible.thread_ids[index] ?? 0,
          title: card.thread_title,
          format: card.thread_format ?? '',
          issue_id: card.issue_id,
          issue_number: card.display_issue_number ?? card.issue_number,
          tags: card.tags ?? [],
          route_labels: card.route_labels?.slice(0, 3) ?? [],
          overflow_routes_count: card.overflow_routes_count ?? 0,
        }]
      })

      // Recovery reads the signed-in reader's browser partition, matching the
      // hook that wrote the selection. The eligible resource intentionally
      // excludes an outstanding server offer, so fetch the exact pending card
      // separately when it is not already a visible face. Its committed read
      // state is also the authoritative oracle for an ambiguous rating.
      const storedPending = readPendingSelection(userId)
      let pendingCard = storedPending != null ? cardByIssue.get(storedPending.issue_id) : undefined
      if (storedPending != null && pendingCard === undefined) {
        pendingCard = (await nativeV2.issueCards({
          body: { issue_ids: [storedPending.issue_id] },
        })).items[0]
        if (pendingCard) cardByIssue.set(pendingCard.issue_id, pendingCard)
      }
      const pending = storedPending != null && pendingCard != null && pendingCard.status !== 'read'
        ? storedPending
        : null
      const blockedIssueId = pending != null && !issueIds.includes(pending.issue_id)
        ? pending.issue_id
        : null
      let recovery: RollRecovery | null = null
      if (blockedIssueId != null) {
        const query: { issue_id: number; snoozed?: string } = { issue_id: blockedIssueId }
        if (snoozes.length > 0) query.snoozed = snoozes.join(',')
        recovery = await nativeV2.recovery({ query })
      }
      const snoozedThreads: RollThreadSummary[] = snoozes.length > 0
        ? (await nativeV2.listThreads({
            query: { ids: snoozes.join(','), page_size: snoozes.length },
          })).threads.flatMap((thread) =>
            snoozes.includes(thread.id) ? [{
              id: thread.id,
              title: thread.title,
              format: thread.format,
            }] : [])
        : []
      const rate = queryClient.getQueryData<RateResponsePayload | null>(queryKeys.roll.lastRead())

      return {
        pending_thread_id: pending?.thread_id ?? null,
        last_rolled_result: pending?.result ?? null,
        session_mode: {
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
        },
        active_thread: null,
        roll_recovery: recovery != null ? parseRollRecovery(recovery) : null,
        roll_pool: rollPool,
        snoozed_threads: snoozedThreads,
        snoozed_count: snoozes.length,
        snoozed_thread_ids: snoozes,
        skipped_thread_ids: [],
        skipped_threads: [],
        pool_reason: eligible.pool_reason,
        last_read: lastRead ?? rate?.roll_reconciliation?.last_read ?? null,
      }
    },
    switchPrerequisite: (request: RollPrerequisiteSwitchRequest) =>
      nativeV2.switchPrerequisite({
        body: { node_type: request.node_type, node_id: request.node_id },
      }),
    /** Retained test hook: browser-owned pending has no client-lifetime dedupe. */
    resetSessionState: (): void => undefined,
  }
}

export const rollStateApi = createRollStateApi(defaultHttpClient())

/** Retained compatibility hook; there is no session-resolution state to clear. */
export function resetRollStateSessionState(): void {
  rollStateApi.resetSessionState()
}
