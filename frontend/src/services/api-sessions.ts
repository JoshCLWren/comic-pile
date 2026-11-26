import { defaultHttpClient, type HttpClient } from './httpClient'
import type { SessionDetails, SessionSnapshotsResponse } from '../types'

/**
 * Build the session service bound to an HTTP client.
 *
 * The legacy session list and single-session reads were retired under #4343
 * (they now 404 in production). Only the supported resource-shaped v2 reads
 * remain; History uses `/api/v2/activity` and SessionPage uses these details
 * and snapshot reads.
 *
 * @param client - HTTP transport used for every request.
 * @returns The session service bound to `client`.
 */
export function createSessionApi(client: HttpClient) {
  return {
    getDetails: (id: number | string) =>
      client.get<SessionDetails>(`/v2/reading-sessions/${id}/details`),
    getSnapshots: (id: number | string) =>
      client.get<SessionSnapshotsResponse>(`/v2/reading-sessions/${id}/snapshots`),
  }
}

export const sessionApi = createSessionApi(defaultHttpClient())
