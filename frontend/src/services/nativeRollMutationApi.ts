import { adaptNativeV2Rate } from './adaptNativeV2Rate'
import { defaultHttpClient, type HttpClient } from './httpClient'
import type { RatePayload, RateResponsePayload } from '../types'
import type { IssueReadRateRequest, IssueReadRateResponse } from '../generated/nativeV2Client'

const RECOVERY_CONFIG = { skipAuthRedirect: true }

/** One rating intent that has not been confirmed yet. */
type UnresolvedRating = {
  issueId: number
  rating: number
  key: string
}

/**
 * Build the retry key for one rating intent.
 *
 * The key is client-generated because the server cannot distinguish a first
 * attempt from a retry of an unanswered one. It is held in memory until the
 * response is confirmed, so an ambiguous network failure replays the original
 * intent instead of rating the same issue twice.
 */
function newRatingKey(): string {
  const bytes = new Uint8Array(16)
  globalThis.crypto.getRandomValues(bytes)
  return `rate-${Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('')}`
}

/**
 * Build the issue-rating service bound to an HTTP client.
 *
 * Every rating - Roll completion and the direct Thread-row rating alike - goes
 * to the live native writer `PATCH /api/v2/issues/{issue_id}`. The request
 * carries an explicit `source`: `roll_offer` applies the Roll completion
 * effects (die step, queue placement, offer linkage) server-side, while
 * `direct` only advances the issue and its thread progress.
 *
 * @param client - HTTP transport used for every rating request.
 * @returns The issue-rating service bound to `client`.
 */
export function createNativeRollMutationApi(client: HttpClient) {
  let unresolved: UnresolvedRating | null = null

  return {
    rate: async (data: RatePayload): Promise<RateResponsePayload> => {
      if (data.issue_id == null) {
        return Promise.reject(new Error('issue_id is required to rate an issue'))
      }
      // A retry of the same unanswered intent reuses its key; a different
      // rating is a new intent and gets a fresh one.
      const key =
        unresolved?.issueId === data.issue_id && unresolved.rating === data.rating
          ? unresolved.key
          : newRatingKey()
      unresolved = { issueId: data.issue_id, rating: data.rating, key }

      const body: IssueReadRateRequest['body'] = {
        status: 'read',
        rating: data.rating,
        idempotency_key: key,
        source: data.source,
      }
      const response = await client.patch<IssueReadRateResponse, typeof body>(
        `/v2/issues/${encodeURIComponent(String(data.issue_id))}`,
        body,
        RECOVERY_CONFIG,
      )
      if (unresolved?.key === key) unresolved = null

      return adaptNativeV2Rate(response)
    },
  }
}

/** The process-wide rating service the app and its tests bind to. */
export const nativeRollMutationApi = createNativeRollMutationApi(defaultHttpClient())
