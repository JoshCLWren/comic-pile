import type { components } from '../generated/openapi'
import { defaultHttpClient, type HttpClient } from './httpClient'

export type ActivityEvent = components['schemas']['ActivityEvent']

export interface ActivityPage {
  events: ActivityEvent[]
  next_page_token: string | null
}

export function createActivityApi(client: HttpClient) {
  return {
    list: (pageToken: string | null = null, pageSize?: number): Promise<ActivityPage> => {
      const params: Record<string, string | number> = {}
      if (pageToken) {
        params.page_token = pageToken
      }
      if (pageSize) {
        params.page_size = pageSize
      }
      return client.get<ActivityPage>('/v2/activity', { params })
    },
  }
}

export const activityApi = createActivityApi(defaultHttpClient())
