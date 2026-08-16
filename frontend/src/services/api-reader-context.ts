import api from './api'

export interface CrossoverMemberInfo {
  issue_id: number
  issue_number: string
  rating: number | null
  status: 'read' | 'unread'
}

export interface LocalChainIssue {
  issue_id: number
  issue_number: string
  position: number
  status: 'read' | 'unread'
  relation: 'previous' | 'current' | 'next' | 'future'
  rating: number | null
  crossover_memberships: CrossoverMemberInfo[]
}

export interface LocalChainEdge {
  dependency_id: number
  source_issue_id: number
  target_issue_id: number
  source_issue_number: string
  target_issue_number: string
  source_thread_id: number
  target_thread_id: number
  source_thread_title: string
  target_thread_title: string
  note: string | null
}

export interface LocalChainResponse {
  issues: LocalChainIssue[]
  edges: LocalChainEdge[]
}

export interface SeriesInfo {
  identity_source: 'comicvine' | 'unavailable'
  canonical_series_id: string | null
  series_name: string | null
  average_rating: number | null
  ratings_count: number
  previous_issue: LocalChainIssue | null
  recent_ratings: LocalChainIssue[]
  highest_rating: number | null
  lowest_rating: number | null
}

export interface CrossoverInfo {
  id: number
  name: string
  applies_to_current_issue: boolean
  next_member: LocalChainIssue | null
  average_rating: number | null
  ratings_count: number
  read_count: number
}

export interface ReaderContextResponse {
  issue_id: number
  series: SeriesInfo
  crossovers: CrossoverInfo[]
  local_chain: LocalChainResponse
}

export const readerContextApi = {
  getForIssue: async (issueId: number): Promise<ReaderContextResponse> => {
    return api.get<ReaderContextResponse>(`/v1/issues/${issueId}/reader-context`)
  }
}
