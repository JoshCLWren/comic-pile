import { defaultHttpClient, type HttpClient } from './httpClient'
import {
  createNativeV2Client,
  type ListActivityRequest,
  type ListActivityResponse,
} from '../generated/nativeV2Client'
import {
  EMPTY_ACTIVITY_FILTERS,
  normalizeActivityFilters,
  type ActivityFilters,
} from '../utils/activityFilters'

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
 * Reader-local timezone resolution for date filters. The browser owns the
 * reader's IANA zone; the server applies it to the inclusive day bounds.
 */
function readerTimeZone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
}

/**
 * @param client - HTTP transport used for every activity request.
 * @returns The activity service bound to `client`.
 */
export function createActivityApi(client: HttpClient) {
  const nativeV2 = createNativeV2Client(client)

  return {
    /**
     * Read one page of the authenticated reader's filtered activity stream.
     *
     * @param pageToken - Opaque continuation token from the previous page.
     * @param filters - Optional reader filters; the unfiltered stream when omitted.
     * @returns The page's logical actions and the next continuation token.
     */
    list: async (
      pageToken: string | null = null,
      filters: ActivityFilters = EMPTY_ACTIVITY_FILTERS,
    ): Promise<ActivityPage> => {
      const query: NonNullable<ListActivityRequest['query']> = { limit: ACTIVITY_PAGE_SIZE }
      if (pageToken) {
        query.page_token = pageToken
      }
      const active = normalizeActivityFilters(filters)
      if (active.q) query.q = active.q
      if (active.series) query.series = active.series
      if (active.type) query.type = active.type
      if (active.dateFrom || active.dateTo) {
        if (active.dateFrom) query.date_from = active.dateFrom
        if (active.dateTo) query.date_to = active.dateTo
        query.timezone = readerTimeZone()
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
