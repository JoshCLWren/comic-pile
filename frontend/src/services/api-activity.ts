import { defaultHttpClient, type HttpClient } from './httpClient'
import type { ActivityResponse } from '../types'

/**
 * Build the activity API service bound to an HTTP client.
 *
 * @param client - HTTP transport used for every request.
 * @returns The activity API service bound to `client`.
 */
export function createActivityApi(client: HttpClient) {
  return {
    /**
     * Fetch the owner-scoped activity timeline.
     * This endpoint returns chronological user activity including sessionless snoozes and ratings.
     *
     * @param pageToken - Optional cursor token for pagination.
     * @param pageSize - Number of events to return per page.
     * @returns The paginated activity response.
     */
    list: async (pageToken?: string | null, pageSize: number = 50): Promise<ActivityResponse> => {
      const params: Record<string, string | number> = { pageSize }
      if (pageToken) {
        params.page_token = pageToken
      }
      const response = await client.get<ActivityResponse>('/api/v2/activity', {
        params,
      })
      return response
    },
  }
}

export const activityApi = createActivityApi(defaultHttpClient())