import type { components } from '../generated/openapi'
import { defaultHttpClient, type HttpClient } from './httpClient'

export type ActivityEvent = components['schemas']['ActivityEvent']

export interface ActivityPage {
  events: ActivityEvent[]
  next_page_token: string | null
}

export function createActivityApi(client: HttpClient) {
  return {
    list: (pageToken: string | null = null, pageSize?: number): Promise<ActivityPage> =>
      client.get<ActivityPage>('/v2/activity', {
        params: {
          ...(pageToken ? { page_token: pageToken } : {}),
          ...(pageSize ? { page_size: pageSize } : {}),
        },
      }),
  }
}

export const activityApi = createActivityApi(defaultHttpClient())
