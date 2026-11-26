import api from './api'

export interface IdentityInboxCandidate {
  external_identity_id: number
  provider: string
  comicvine_id: string | null
  external_url: string | null
  metadata_json: Record<string, string | Record<string, string> | null>
  status: string
  confidence: number | null
  evidence_source: string | null
  evidence_json: Record<string, string | string[] | null>
  rejection_reason: string | null
}

export interface IdentityInboxItem {
  mapping_id: number
  issue_id: number
  thread_id: number
  thread_title: string
  issue_number: string
  status: string
  provider: string | null
  source_entry_summary: string
  why_stopped: string
  next_steps?: string[]
  candidates: IdentityInboxCandidate[]
  created_at: number | null
  updated_at: number | null
}

export interface IdentityInboxResponse {
  items: IdentityInboxItem[]
  total: number
  offset: number
  limit: number
}

export interface IdentityInboxSearchResult {
  comicvine_issue_id: number
  comicvine_volume_id: number | null
  volume_name: string | null
  issue_number: string | null
  issue_name: string | null
  publisher: string | null
  start_year: number | null
  site_detail_url: string | null
  image_url: string | null
  score: number | null
  evidence: string[]
}

export interface IdentityInboxPartialMatchIssue {
  issue_id: number
  issue_number: string
  comicvine_issue_id: number
  mapping_id: number | null
  external_identity_id: number | null
  reason: string
}

export interface IdentityInboxPartialMatch {
  comicvine_volume_id: number
  volume_name: string
  actionable_reason: string
  matched: IdentityInboxPartialMatchIssue[]
  unmatched: IdentityInboxPartialMatchIssue[]
}

export interface IdentityInboxSearchResponse {
  issue_id: number
  query: string
  results: IdentityInboxSearchResult[]
  total_available: number | null
  partial_matches: IdentityInboxPartialMatch[]
  no_match_reason: string | null
}

export interface IdentityInboxConfirmPayload {
  external_identity_id: number
}

export interface IdentityInboxRejectPayload {
  external_identity_id: number
  rejection_reason: string
}

export const identityInboxApi = {
  list: (offset: number, limit: number) =>
    api.get<IdentityInboxResponse>('/v2/identity-inbox', { params: { offset, limit } }),
  searchMatches: (query: string, issueId: number) =>
    api.get<IdentityInboxSearchResponse>('/v2/identity-inbox/issue-matches', {
      params: { q: query, issue_id: issueId, limit: 20 },
    }),
  confirm: (mappingId: number, payload: IdentityInboxConfirmPayload) =>
    api.post<void>(`/v2/identity-inbox/${mappingId}/confirmations`, payload),
  reject: (mappingId: number, payload: IdentityInboxRejectPayload) =>
    api.post<void>(`/v2/identity-inbox/${mappingId}/rejections`, payload),
  defer: (mappingId: number) =>
    api.post<void>(`/v2/identity-inbox/${mappingId}/deferrals`),
  skip: (mappingId: number) =>
    api.post<void>(`/v2/identity-inbox/${mappingId}/skips`),
}