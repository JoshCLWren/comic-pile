import { defaultHttpClient, type HttpClient } from './httpClient'
import {
  createNativeV2Client,
  type GetReadingSessionResponse,
  type ListReadingSessionsRequest,
} from '../generated/nativeV2Client'
/** One durable, event-derived reading session from the canonical collection. */
export type ReadingSession = GetReadingSessionResponse

/** One bounded page of the canonical reading-session collection. */
export type ReadingSessionPage = {
  items: ReadingSession[]
  next_page_token: string | null
}

/** Stable page size for every canonical reading-session list request. */
export const READING_SESSION_PAGE_SIZE = 50

/**
 * Build the session service bound to an HTTP client.
 *
 * Every method uses the generated native v2 client so the canonical
 * lowerCamelCase `readingSessions` resource owns the URL and query contract.
 * The retired v1 session list/current/single reads remain retired (#4343): the
 * List/Get methods below are the event-derived history resource required by
 * #5708, with no server session lifetime or pending state. History's stream
 * stays on `/api/v2/activity`; session-scoped drill-down uses these reads.
 *
 * @param client - HTTP transport used for every request.
 * @returns The session service bound to `client`.
 */
export function createSessionApi(client: HttpClient) {
  const nativeV2 = createNativeV2Client(client)

  return {
    /**
     * Read one page of the authenticated reader's sessions.
     *
     * @param pageToken - Opaque continuation token from the previous page.
     * @returns The page's sessions and next continuation token.
     */
    list: async (pageToken: string | null = null): Promise<ReadingSessionPage> => {
      const query: NonNullable<ListReadingSessionsRequest['query']> = {
        page_size: READING_SESSION_PAGE_SIZE,
      }
      if (pageToken) {
        query.page_token = pageToken
      }
      const response = await nativeV2.listReadingSessions({ query })
      return {
        items: response.reading_sessions,
        next_page_token: response.next_page_token ?? null,
      }
    },

    /**
     * Read one owned session as an event-derived resource.
     *
     * @param id - Stable session id from the collection.
     * @returns The session resource.
     */
    get: (id: number | string) =>
      nativeV2.getReadingSession({ path: { session_id: Number(id) } }),

    /**
     * Read the full recorded dice/read timeline for one owned session.
     *
     * @param id - Stable session id.
     * @returns The session details projection.
     */
    getDetails: (id: number | string) =>
      nativeV2.getSessionDetails({ path: { session_id: Number(id) } }),

    /**
     * Read the restore snapshots for one owned session.
     *
     * @param id - Stable session id.
     * @returns The session's snapshots.
     */
    getSnapshots: (id: number | string) =>
      nativeV2.listSessionSnapshots({ path: { session_id: Number(id) } }),
  }
}

export const sessionApi = createSessionApi(defaultHttpClient())
