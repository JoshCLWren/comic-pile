import { createNativeV2Client } from '../generated/nativeV2Client'
import type { HttpClient } from './httpClient'
import type { RatePayload, RateResponsePayload, Thread } from '../types'
import type { IssueReadRateResponse } from '../generated/nativeV2Client'

const RECOVERY_CONFIG = { skipAuthRedirect: true }

/**
 * Adapt native IssueReadRateResponse to Python-compatible RateResponsePayload shape.
 * The native response has a subset of fields; we construct a compatible thread object
 * using the thread progress and issue data from the native response.
 */
function adaptNativeRateResponse(native: IssueReadRateResponse): RateResponsePayload {
  const threadProgress = native.thread
  const issue = native.issue

  // Construct a thread object compatible with Python's RateResponse
  // The native response provides the essential fields; we fill in the rest with defaults
  // where the Python service would compute them. The authoritative bootstrap refresh
  // will provide the complete thread state shortly after.
  const adaptedThread: Thread & { roll_reconciliation?: { last_read: { issue_id: number; issue_number: string; thread_id: number; thread_title: string; read_at: string; cover_url?: string | null } } } = {
    id: threadProgress.thread_id,
    title: issue.thread_title,
    format: '', // Will be filled by bootstrap refresh
    issues_remaining: threadProgress.issues_remaining,
    queue_position: 0, // Will be filled by bootstrap refresh
    status: threadProgress.status,
    last_rating: threadProgress.last_rating ?? null,
    last_activity_at: issue.read_at ?? new Date().toISOString(),
    notes: null,
    is_test: false,
    is_blocked: false,
    created_at: new Date().toISOString(),
    total_issues: null,
    reading_progress: threadProgress.reading_progress ?? null,
    next_unread_issue_id: threadProgress.next_unread_issue_id ?? null,
    next_unread_issue_number: null,
    manual_creator_credits: [],
    blocking_reasons: [],
    roll_reconciliation: native.read_event_created
      ? {
          last_read: {
            issue_id: issue.issue_id,
            issue_number: issue.issue_number,
            thread_id: threadProgress.thread_id,
            thread_title: issue.thread_title,
            read_at: issue.read_at ?? new Date().toISOString(),
            cover_url: issue.cover_image_url ?? null,
          },
        }
      : undefined,
  }

  return adaptedThread as RateResponsePayload
}

/**
 * Build the native Roll mutation service bound to an HTTP client.
 * Uses PATCH /api/v2/issues/{issue_id} with source="roll_offer" for Roll completion.
 *
 * @param client - HTTP transport used for every request.
 * @returns The native Roll mutation service bound to `client`.
 */
export function createNativeRollMutationApi(client: HttpClient) {
  const nativeClient = createNativeV2Client(client)

  return {
    /**
     * Rate an issue from a Roll offer.
     * Uses PATCH /api/v2/issues/{issue_id} with source="roll_offer".
     */
    rateRollOffer: async (data: RatePayload & { issue_id: number; idempotency_key: string }): Promise<RateResponsePayload> => {
      const { issue_id, idempotency_key, ...rest } = data
      const nativeResponse = await nativeClient.issueReadRate({
        path: { issue_id },
        body: {
          status: 'read',
          rating: rest.rating,
          idempotency_key,
          source: 'roll_offer' as const,
        },
      })
      return adaptNativeRateResponse(nativeResponse)
    },

    /**
     * Rate an issue directly (not from a Roll offer).
     * Uses PATCH /api/v2/issues/{issue_id} with source="direct".
     */
    rateDirect: async (data: RatePayload & { issue_id: number; idempotency_key: string }): Promise<RateResponsePayload> => {
      const { issue_id, idempotency_key, ...rest } = data
      const nativeResponse = await nativeClient.issueReadRate({
        path: { issue_id },
        body: {
          status: 'read',
          rating: rest.rating,
          idempotency_key,
          source: 'direct',
        },
      })
      return adaptNativeRateResponse(nativeResponse)
    },
  }
}

export type NativeRollMutationApi = ReturnType<typeof createNativeRollMutationApi>