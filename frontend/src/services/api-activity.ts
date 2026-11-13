import { defaultHttpClient, type HttpClient } from './httpClient'

export interface ActivityEvent {
  event_id: number
  event_type: string
  timestamp: string
  die_before: number | null
  die_after: number | null
  rating: number | null
  thread_id: number | null
  thread_title: string | null
  issue_id: number | null
  issue_number: string | null
  action_display: string
}

export interface ActivityPage {
  events: ActivityEvent[]
  next_page_token: string | null
}

export function createActivityApi(client: HttpClient) {
  return {
    list: (pageToken: string | null = null): Promise<ActivityPage> =>
      client.get<ActivityPage>('/v2/activity', {
        params: pageToken ? { page_token: pageToken } : undefined,
      }),
  }
}

export const activityApi = createActivityApi(defaultHttpClient())
