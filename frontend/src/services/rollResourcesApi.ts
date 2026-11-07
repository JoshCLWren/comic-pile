import {
  createNativeV2Client,
  type DieStateResponse,
  type EligibleIssueIdsResponse,
  type IssueCardsResponse,
} from '../generated/nativeV2Client'
import { defaultHttpClient, type HttpClient } from './httpClient'

export type { DieStateResponse, EligibleIssueIdsResponse, IssueCardsResponse }

/**
 * Build the scoped Roll resource service bound to an HTTP client.
 *
 * The generated native v2 client owns the URL, method and body contract for
 * `GET /v2/roll/die-state`, `GET /v2/roll/eligible-issue-ids` and
 * `POST /v2/issues/cards`. This adapter keeps reader-facing argument shapes:
 * browser-owned temporary snoozes as thread ids, and a bounded batch of
 * visible issue ids. It does not replace the bootstrap read yet; it is the
 * production caller the scoped resources were shipped for, so the next
 * Roll migration can switch surfaces without hand-written URL strings.
 *
 * @param client - HTTP transport used for every Roll resource request.
 * @returns The Roll resources service bound to `client`.
 */
export function createRollResourcesApi(client: HttpClient) {
  const nativeV2 = createNativeV2Client(client)

  return {
    dieState: (): Promise<DieStateResponse> => nativeV2.dieState(),
    eligibleIssueIds: (snoozedThreadIds: readonly number[] = []): Promise<EligibleIssueIdsResponse> =>
      nativeV2.eligibleIssueIds({
        query: snoozedThreadIds.length > 0 ? { snoozed: snoozedThreadIds.join(',') } : {},
      }),
    issueCards: (issueIds: readonly number[]): Promise<IssueCardsResponse> =>
      nativeV2.issueCards({ body: { issue_ids: [...issueIds] } }),
  }
}

export type RollResourcesApi = ReturnType<typeof createRollResourcesApi>

export const rollResourcesApi = createRollResourcesApi(defaultHttpClient())
