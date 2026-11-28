import {
  createNativeV2Client,
  type GetIssueDependenciesResponse,
  type IssueCardsResponse,
  type ReadingGraphResponse,
} from '../generated/nativeV2Client'
import { defaultHttpClient, type HttpClient } from './httpClient'
import { readRollSnoozes } from './api-roll'
import { readPendingSelection } from './rollPendingSelection'
import { buildRollRecovery } from './rollRecovery'
import { queryClient } from '../query/queryClient'
import { queryKeys } from '../query/queryKeys'
import type { RateResponsePayload } from '../types'
import type { RollPendingUserId } from './apiTypes'
import type {
  RollBootstrapResponse,
  RollBootstrapThread,
  RollPrerequisiteSwitchRequest,
} from '../types/rollBootstrap'

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
export function createRollBootstrapApi(client: HttpClient) {
  const nativeV2 = createNativeV2Client(client)

  return {
    get: async (userId?: RollPendingUserId): Promise<RollBootstrapResponse> => {
      const [eligible, snoozes] = await Promise.all([
        nativeV2.eligibleIssueIds({
          query: readRollSnoozes().length > 0
            ? { snoozed: readRollSnoozes().join(',') }
            : {},
        }),
        Promise.resolve(readRollSnoozes()),
      ])
      const issueIds = eligible.issue_ids
      const cards = issueIds.length > 0
        ? await nativeV2.issueCards({ body: { issue_ids: issueIds } })
        : { items: [] }
      const cardByIssue = new Map(cards.items.map((card) => [card.issue_id, card]))
      const rollPool: RollBootstrapThread[] = issueIds.flatMap((issueId, index) => {
        const card = cardByIssue.get(issueId)
        if (!card) return []
        return [{
          id: card.thread_id ?? eligible.thread_ids[index] ?? 0,
          title: card.thread_title,
          format: '',
          issue_id: card.issue_id,
          issue_number: card.display_issue_number ?? card.issue_number,
          tags: [],
          route_labels: [],
          overflow_routes_count: 0,
        }]
      })

      // Recovery reads the signed-in reader's browser partition, matching the
      // hook that wrote the selection. A blocked pending issue is the only case
      // that needs an extra scoped request.
      const pending = readPendingSelection(userId)
      const blockedIssueId = pending != null && !issueIds.includes(pending.issue_id)
        ? pending.issue_id
        : null
      let dependencies: GetIssueDependenciesResponse | null = null
      let prerequisiteCards: IssueCardsResponse['items'] = []
      if (blockedIssueId != null) {
        dependencies = await nativeV2.getIssueDependencies({
          path: { issue_id: blockedIssueId },
        })
        const sourceIds = [...new Set(dependencies.incoming.map((edge) => edge.source_issue_id))]
        if (sourceIds.length > 0) {
          prerequisiteCards = (await nativeV2.issueCards({
            body: { issue_ids: sourceIds },
          })).items
        }
      }
      const graph = queryClient.getQueryData<ReadingGraphResponse>(
        queryKeys.readingGraph.status(),
      ) ?? null
      const rate = queryClient.getQueryData<RateResponsePayload | null>(queryKeys.roll.lastRead())
      const recovery = pending != null
        ? buildRollRecovery({
            pending,
            eligibleIssueIds: issueIds,
            dependencies,
            prerequisiteCards,
            graph,
            originalTitle: rollPool.find((thread) => thread.issue_id === pending.issue_id)?.title ?? null,
          })
        : null

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
        roll_recovery: recovery,
        roll_pool: rollPool,
        snoozed_threads: [],
        snoozed_count: snoozes.length,
        snoozed_thread_ids: snoozes,
        skipped_thread_ids: [],
        skipped_threads: [],
        pool_reason: eligible.pool_reason,
        last_read: rate?.roll_reconciliation?.last_read ?? null,
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

export const rollBootstrapApi = createRollBootstrapApi(defaultHttpClient())

/** Retained compatibility hook; there is no session-resolution state to clear. */
export function resetRollBootstrapSessionState(): void {
  rollBootstrapApi.resetSessionState()
}
