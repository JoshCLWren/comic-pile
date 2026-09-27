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

export interface IdentityInboxConfirmPayload {
  external_identity_id: number
}

export interface IdentityInboxRejectPayload {
  external_identity_id: number
  rejection_reason: string
}

export const identityInboxApi = {
  list: (offset: number, limit: number) =>
    api.get<IdentityInboxResponse>('/v1/identity-inbox', { params: { offset, limit } }),
  confirm: (mappingId: number, payload: IdentityInboxConfirmPayload) =>
    api.post<void>(`/v1/identity-inbox/${mappingId}/confirm`, payload),
  reject: (mappingId: number, payload: IdentityInboxRejectPayload) =>
    api.post<void>(`/v1/identity-inbox/${mappingId}/reject`, payload),
  defer: (mappingId: number) =>
    api.post<void>(`/v1/identity-inbox/${mappingId}/defer`),
  skip: (mappingId: number) =>
    api.post<void>(`/v1/identity-inbox/${mappingId}/skip`),
}