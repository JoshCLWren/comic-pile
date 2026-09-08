import api from './api'

export interface CBLSourceListDiscoveryItem {
  id: number
  name: string
  source_path: string
  source_repository: string
  declared_issue_count: number | null
  content_hash: string
  revision_sha: string
}

export type CBLAdoptionClass = 'existing' | 'missing_importable' | 'ambiguous_unresolved'
export type CBLAdoptionDecision =
  | 'included_existing'
  | 'would_create_missing'
  | 'awaiting_opt_in'
  | 'excluded'
  | 'unresolved'

export interface CBLAdoptionPreviewEntry {
  cbl_position: number
  cbl_entry_id: number
  series_name: string
  issue_number: string
  series_group_id: string
  adoption_class: CBLAdoptionClass
  adoption_decision: CBLAdoptionDecision
  adopted: boolean
  comicvine_issue_id: string | null
  comicvine_series_id: string | null
  series_provider: string | null
  series_external_id: string | null
  resolved_issue_id: number | null
  canonical_issue_id: number | null
  read_status: string | null
  read_at: string | null
  resolution_status: string
  is_duplicate_identity: boolean
}

export interface CBLAdoptionPreview {
  source: {
    source_list_id: number
    source_repository: string
    source_path: string
    content_hash: string
    revision_sha: string
  }
  total_positions: number
  entries: CBLAdoptionPreviewEntry[]
  summary: {
    reused_existing_count: number
    missing_would_create_count: number
    excluded_count: number
    unresolved_count: number
    awaiting_opt_in_count: number
    final_adopted_count: number
    final_adopted_order: number[]
    reused_existing_positions: number[]
    missing_would_create_positions: number[]
    excluded_positions: number[]
    unresolved_positions: number[]
    awaiting_opt_in_positions: number[]
  }
}

export const cblSourcesApi = {
  discover: (query: string, limit = 25) =>
    api.get<CBLSourceListDiscoveryItem[]>('/v1/issue-identity/cbl-sources', {
      params: { q: query, limit },
    }),
  preview: (listId: number) =>
    api.get<CBLAdoptionPreview>(`/v1/issue-identity/cbl/${listId}/adoption-preview`),
}
