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

export interface CBLReadingPlanCommitResult {
  plan_id: number
  source_list_id: number
  reused_issue_ids: number[]
  added_issue_ids: number[]
  created_issue_ids: number[]
  created_thread_ids: number[]
  excluded_source_positions: number[]
  unresolved_source_positions: number[]
  awaiting_opt_in_source_positions: number[]
  final_adopted_source_positions: number[]
  idempotent_replay: boolean
}

interface CBLAdoptionPlanChoices {
  series_decisions: Record<string, boolean>
  entry_decisions: Record<string, boolean>
}

export const cblSourcesApi = {
  discover: (query: string, limit = 25) =>
    api.get<CBLSourceListDiscoveryItem[]>('/v1/issue-identity/cbl-sources', {
      params: { q: query, limit },
    }),
  preview: (listId: number) =>
    api.get<CBLAdoptionPreview>(`/v1/issue-identity/cbl/${listId}/adoption-preview`),
  plan: (listId: number, choices: CBLAdoptionPlanChoices) =>
    api.post<CBLAdoptionPreview>(`/v1/issue-identity/cbl/${listId}/adoption-plan`, choices),
  commit: (
    listId: number,
    planId: number,
    preview: CBLAdoptionPreview,
    choices: CBLAdoptionPlanChoices,
  ) =>
    api.post<CBLReadingPlanCommitResult>(
      `/v1/issue-identity/cbl-sources/${listId}/reading-plans/${planId}/commit`,
      {
        source: preview.source,
        reviewed_entries: preview.entries,
        reviewed_final_positions: preview.summary.final_adopted_order,
        series_decisions: choices.series_decisions,
        entry_decisions: choices.entry_decisions,
      },
    ),
}
