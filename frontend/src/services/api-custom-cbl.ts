import api from './api'
import type { HttpClient } from './httpClient'
import type { ContinuityPlan } from './api-continuity-plans'

export interface CustomCBLEntry {
  id: number
  position: number
  issue_id: number
  thread_id: number
  series_name: string
  issue_number: string
  status: string
}

export interface CustomCBLListItem {
  id: number
  name: string
  description: string | null
  issue_count: number
  updated_at: string
}

export interface CustomCBL extends CustomCBLListItem {
  user_id: number
  created_at: string
  entries: CustomCBLEntry[]
}

export interface CustomCBLIssueSearchResult {
  issue_id: number
  thread_id: number
  series_name: string
  issue_number: string
  status: string
}

export interface CustomCBLWrite {
  name: string
  description?: string | null
  issue_ids: number[]
}

export interface CustomCBLApplyResult extends ContinuityPlan {
  added_issue_ids: number[]
  skipped_existing_issue_ids: number[]
}

/**
 * Build the custom-CBL service bound to an HTTP client.
 *
 * @param client - HTTP transport used for every custom-CBL request.
 * @returns The custom CBL API bound to `client`.
 */
export function createCustomCBLApi(client: HttpClient) {
  return {
    list: () => client.get<CustomCBLListItem[]>('/v1/custom-cbls'),
    get: (listId: number) => client.get<CustomCBL>(`/v1/custom-cbls/${listId}`),
    create: (payload: CustomCBLWrite) => client.post<CustomCBL>('/v1/custom-cbls', payload),
    update: (listId: number, payload: CustomCBLWrite) =>
      client.put<CustomCBL>(`/v1/custom-cbls/${listId}`, payload),
    delete: (listId: number) => client.delete<void>(`/v1/custom-cbls/${listId}`),
    searchIssues: (query: string, limit = 30) =>
      client.get<CustomCBLIssueSearchResult[]>('/v1/custom-cbls/issue-search', {
        params: { q: query, limit },
      }),
    apply: (listId: number, planId: number, laneId?: string | null) =>
      client.post<CustomCBLApplyResult>(
        `/v1/custom-cbls/${listId}/reading-plans/${planId}:apply`,
        { lane_id: laneId ?? null },
      ),
    exportXml: (listId: number) =>
      client.get<string>(`/v1/custom-cbls/${listId}/export`, { responseType: 'text' }),
  }
}

export const customCBLApi = createCustomCBLApi(api)
