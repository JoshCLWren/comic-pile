import { createNativeV2Client, type IssueCardsResponse } from '../generated/nativeV2Client'
import { defaultHttpClient, type HttpClient } from './httpClient'

/**
 * Build the issue-card batch service bound to an HTTP client.
 *
 * The generated native v2 client owns the URL, method and body contract; this
 * adapter feeds the bounded `POST /v2/issues/cards` batch the Thread issue
 * rows use to display persisted ratings after reload (#4204). One call covers
 * every visible issue id, so rows never issue one request each.
 *
 * @param client - HTTP transport used for every cards request.
 * @returns The issue-card batch service bound to `client`.
 */
export function createIssueCardsApi(client: HttpClient) {
  const nativeV2 = createNativeV2Client(client)

  return {
    /**
     * Read the owner-scoped cards for a bounded set of issue ids.
     * @param issueIds - Visible issue identifiers (1-200 per request).
     * @returns The cards in first-request order, with per-issue ratings.
     */
    cards: (issueIds: number[]): Promise<IssueCardsResponse> =>
      nativeV2.issueCards({ body: { issue_ids: issueIds } }),
  }
}

/** The process-wide cards service the app and its tests bind to. */
export const issueCardsApi = createIssueCardsApi(defaultHttpClient())
