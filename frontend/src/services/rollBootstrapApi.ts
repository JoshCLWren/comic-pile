import { createNativeV2Client } from '../generated/nativeV2Client'
import { defaultHttpClient, type HttpClient } from './httpClient'
import { readRollSnoozes } from './api-roll'
import { readPendingSelection } from './rollPendingSelection'
import type {
  RollBootstrapResponse,
  RollBootstrapThread,
  RollPrerequisiteSwitchRequest,
  RollPrerequisiteSwitchResponse,
} from '../types/rollBootstrap'

/**
 * Client-side composition of the scoped Roll resources.
 *
 * Retired aggregate and session-init requests are gone: this service reads only
 * `GET /v2/roll/die-state`, `GET /v2/roll/eligible-issue-ids` and
 * `POST /v2/issues/cards`, then joins the browser-owned pending selection. It is
 * kept as a service seam so mutation reconciliation and its tests can ask for
 * the current view without reaching into React hooks.
 */
export function createRollBootstrapApi(client: HttpClient) {
  const nativeV2 = createNativeV2Client(client)

  return {
    get: async (userId?: number | string | null): Promise<RollBootstrapResponse> => {
      const [dieState, eligible, snoozes] = await Promise.all([
        nativeV2.dieState(),
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
      const pending = readPendingSelection(userId)
      return {
        session_id: 0,
        user_id: 0,
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
        roll_recovery: null,
        roll_pool: rollPool,
        snoozed_threads: [],
        snoozed_count: snoozes.length,
        snoozed_thread_ids: snoozes,
        skipped_thread_ids: [],
        skipped_threads: [],
        pool_reason: eligible.pool_reason,
      }
    },
    switchPrerequisite: (request: RollPrerequisiteSwitchRequest) =>
      nativeV2.switchPrerequisite({
        body: { node_type: request.node_type, node_id: request.node_id },
      }) as Promise<RollPrerequisiteSwitchResponse>,
    /** Retained test hook: browser-owned pending has no client-lifetime dedupe. */
    resetSessionState: (): void => undefined,
  }
}

export const rollBootstrapApi = createRollBootstrapApi(defaultHttpClient())

/** Retained compatibility hook; there is no session-resolution state to clear. */
export function resetRollBootstrapSessionState(): void {
  rollBootstrapApi.resetSessionState()
}
