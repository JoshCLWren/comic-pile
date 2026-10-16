import { defaultHttpClient, type HttpClient } from './httpClient'
import type { ContinuityPlan } from './api-continuity-plans'

/** Strict lists gate every entry on all earlier entries; loose lists only gate explicit intents. */
export type ReadingListMode = 'strict' | 'loose'

/** Positional intent for one member Issue in a Reading List. */
export type ReadingListGate = 'none' | 'hold' | 'after_previous'

export interface ReadingListEntryIntent {
  gate: ReadingListGate
  skipped: boolean
}

/** Named before/after stored requirements the reader must acknowledge before a semantic save. */
export interface ReadingListPredecessorChange {
  issue_id: number
  issue_name: string
  before_issue_ids: number[]
  before_issue_names: string[]
  after_issue_ids: number[]
  after_issue_names: string[]
}

/** One structured edge in a rejected cycle path. */
export interface ReadingListCycleEdge {
  source_issue_id: number
  source_issue_name?: string
  target_issue_id: number
  target_issue_name?: string
  origin: string | null
  prerequisite_origin: 'reader' | 'converted' | null
  provenance: string[]
}

export interface CustomCBLEntry {
  id: number
  position: number
  issue_id: number
  thread_id: number
  series_name: string
  issue_number: string
  status: string
  is_checkpoint?: boolean
  checkpoint_target_issue_ids?: number[]
  gate: ReadingListGate
  skipped: boolean
}

export interface CustomCBLListItem {
  id: number
  name: string
  description: string | null
  mode: ReadingListMode
  issue_count: number
  updated_at: string
}

export interface CustomCBL extends CustomCBLListItem {
  user_id: number
  created_at: string
  entries: CustomCBLEntry[]
  predecessor_changes?: ReadingListPredecessorChange[]
  warnings?: string[]
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
  mode?: ReadingListMode
  issue_ids: number[]
  entry_intents?: Record<number, ReadingListEntryIntent>
  checkpoint_issue_ids?: number[]
  checkpoint_targets?: Record<number, number[]>
  confirmed_predecessor_changes?: ReadingListPredecessorChange[]
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

export const customCBLApi = createCustomCBLApi(defaultHttpClient())
