import { defaultHttpClient, type HttpClient } from './httpClient'
import {
  createNativeV2Client,
  type ListActivityRequest,
  type ListActivityResponse,
} from '../generated/nativeV2Client'

/**
 * One reader-visible logical action from `GET /api/v2/activity`.
 *
 * The native resource already coalesces the durable command pairs (snooze and
 * its resulting roll, rating receipt and its dice step) into one item each, so
 * the UI renders `items` exactly as returned instead of merging rows itself.
 */
export type ActivityItem = ListActivityResponse['items'][number]

/** One bounded page of the owner-scoped activity stream. */
export type ActivityPage = {
  items: ActivityItem[]
  next_page_token: string | null
}

/** Stable page size for every History request. */
export const ACTIVITY_PAGE_SIZE = 50

/**
 * Build the activity service bound to an HTTP client.
 *
 * The generated native v2 client owns the URL, method, and query contract for
 * `GET /v2/activity`; this adapter only keeps the reader-facing page shape and
 * the explicit page size History requests.
 *
 * @param client - HTTP transport used for every activity request.
 * @returns The activity service bound to `client`.
 */
export function createActivityApi(client: HttpClient) {
  const nativeV2 = createNativeV2Client(client)

  return {
    /**
     * Read one page of the authenticated reader's activity stream.
     *
     * @param pageToken - Opaque continuation token from the previous page.
     * @returns The page's logical actions and the next continuation token.
     */
    list: async (pageToken: string | null = null): Promise<ActivityPage> => {
      const query: NonNullable<ListActivityRequest['query']> = { limit: ACTIVITY_PAGE_SIZE }
      if (pageToken) {
        query.page_token = pageToken
      }
      const response = await nativeV2.listActivity({ query })
      return {
        items: response.items,
        next_page_token: response.next_page_token ?? null,
      }
    },
  }
}

/** Activity service surface the History page depends on. */
export type ActivityApi = ReturnType<typeof createActivityApi>

export const activityApi = createActivityApi(defaultHttpClient())
