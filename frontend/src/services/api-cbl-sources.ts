import { defaultHttpClient, type HttpClient } from './httpClient'
import type { ContinuityPlan } from './api-continuity-plans'

export interface CBLSourceListDiscoveryItem {
  id: number
  name: string
  source_path: string
  source_repository: string
  declared_issue_count: number | null
  content_hash: string
  revision_sha: string
}

export interface CBLSourceEntryDetail {
  position: number
  series_name: string
  issue_number: string
  volume_year: number | null
  publication_year: number | null
  comicvine_issue_id: string | null
  comicvine_volume_id: string | null
}

export interface CBLSourceListDetail {
  id: number
  name: string
  source_path: string
  source_repository: string
  source_ref: string
  declared_issue_count: number | null
  content_hash: string
  revision_sha: string
  entries_total: number
  entries_offset: number
  entries_limit: number
  entries: CBLSourceEntryDetail[]
}

export interface CBLComicvineOccurrence {
  list_id: number
  list_name: string
  source_path: string
  source_repository: string
  source_ref: string
  revision_sha: string
  position: number
  series_name: string
  issue_number: string
  volume_year: number | null
  publication_year: number | null
  comicvine_issue_id: string
  comicvine_volume_id: string | null
}

export interface CBLComicvineOccurrencePage {
  comicvine_issue_id: string
  occurrences_total: number
  lists_total: number
  occurrences_offset: number
  occurrences_limit: number
  occurrences: CBLComicvineOccurrence[]
}

export type CBLCoverageOrderStatus = 'same_order' | 'reordered' | 'not_comparable'

export interface CBLSourceComparisonMatch {
  list_id: number
  list_name: string
  source_path: string
  source_repository: string
  source_ref: string
  revision_sha: string
  declared_issue_count: number | null
  entries_total: number
  distinct_source_issues: number
  matched_input_count: number
  input_total: number
  matched_occurrence_count: number
  duplicate_match_count: number
  source_only_issue_count: number
  input_coverage_percentage: number
  source_coverage_percentage: number
  order_status: CBLCoverageOrderStatus
  order_pair_count: number
  order_disagreement_count: number
  matched_input_ids: string[]
  missing_input_ids: string[]
  score: number
}

export interface CBLSourceComparisonResponse {
  comicvine_issue_ids: string[]
  input_total: number
  candidates_total: number
  candidates: CBLSourceComparisonMatch[]
}

export type CBLReadingListIdentityStatus = 'confirmed' | 'missing' | 'conflict'

export interface CBLReadingListInputEntry {
  position: number
  issue_id: number
  series_name: string
  issue_number: string
  comicvine_issue_id: string | null
  comicvine_issue_ids: string[]
  identity_status: CBLReadingListIdentityStatus
}

export interface CBLReadingListCandidatesResponse {
  list_id: number
  list_name: string
  input_entry_count: number
  input_confirmed_total: number
  input_missing_count: number
  input_conflict_count: number
  input_ids: string[]
  entries: CBLReadingListInputEntry[]
  candidates_total: number
  candidates: CBLSourceComparisonMatch[]
}

export type CBLAdoptionClass = 'existing' | 'missing_importable' | 'ambiguous_unresolved'
export type CBLAdoptionDecision =
  | 'included_existing'
  | 'would_create_missing'
  | 'awaiting_opt_in'
  | 'excluded'
  | 'unresolved'

export interface CBLAdoptionPreviewEntry {
  collection_excluded?: boolean
  collection_exclusion_reason?: string | null
  collection_exclusion_ids?: number[]
  cbl_position: number
  cbl_entry_id: number
  series_name: string
  issue_number: string
  series_group_id: string
  volume_year?: number | null
  publication_year?: number | null
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

export interface CBLAdoptionCommitResult extends ContinuityPlan {
  reused_positions: number[]
  created_positions: number[]
  excluded_positions: number[]
  unresolved_positions: number[]
}

export interface CBLAdoptionPlanChoices {
  series_decisions: Record<string, boolean>
  entry_decisions: Record<string, boolean>
}

/**
 * Build the CBL source service bound to an HTTP client.
 *
 * @param client - HTTP transport used for every request.
 * @returns The CBL source service bound to `client`.
 */
export function createCblSourcesApi(client: HttpClient) {
  /**
   * Expand reader choices into the per-position override payload the commit
   * endpoints expect. Identity-aware group decisions are expanded so two runs
   * that share a series_name cannot collapse on the backend.
   */
  const commitPayload = (
    preview: CBLAdoptionPreview,
    choices: CBLAdoptionPlanChoices,
  ) => {
    const entriesById = new Map(
      preview.entries.map((entry) => [String(entry.cbl_entry_id), entry]),
    )
    const overridesByPosition = new Map<number, 'include' | 'exclude'>()
    for (const [groupId, include] of Object.entries(choices.series_decisions)) {
      const decision = include ? 'include' : 'exclude'
      for (const entry of preview.entries) {
        if (entry.series_group_id === groupId) {
          overridesByPosition.set(entry.cbl_position, decision)
        }
      }
    }
    for (const [entryId, include] of Object.entries(choices.entry_decisions)) {
      const entry = entriesById.get(entryId)
      if (entry) {
        overridesByPosition.set(entry.cbl_position, include ? 'include' : 'exclude')
      }
    }
    const seriesOverrides = [...overridesByPosition.entries()]
      .sort(([left], [right]) => left - right)
      .map(([cbl_position, decision]) => ({ cbl_position, decision }))
    return {
      entry_decisions: {},
      series_decisions: [],
      series_overrides: seriesOverrides,
      content_hash: preview.source.content_hash,
      revision_sha: preview.source.revision_sha,
    }
  }
  return {
    discover: (query: string, limit = 25) =>
      client.get<CBLSourceListDiscoveryItem[]>('/v1/issue-identity/cbl-sources', {
        params: { q: query, limit },
      }),
    /** Read one shared source list and its ordered occurrences (read-only). */
    detail: (listId: number, options?: { offset?: number; limit?: number }) =>
      client.get<CBLSourceListDetail>(`/v1/issue-identity/cbl-sources/${listId}`, {
        params: options,
      }),
    /** Find every shared source occurrence that holds one exact Comic Vine issue ID. */
    findByComicvineIssue: (
      comicvineIssueId: string,
      options?: { offset?: number; limit?: number },
    ) =>
      client.get<CBLComicvineOccurrencePage>(
        `/v1/issue-identity/cbl-sources/by-comicvine-issue/${encodeURIComponent(comicvineIssueId)}`,
        { params: options },
      ),
    /** Rank shared sources by distinct coverage and relative order. */
    compare: (comicvineIssueIds: string[], limit = 50) =>
      client.post<CBLSourceComparisonResponse>(
        '/v1/issue-identity/cbl-sources/compare',
        { comicvine_issue_ids: comicvineIssueIds },
        { params: { limit } },
      ),
    /** Compare one owned Reading List's confirmed identities to shared sources. */
    readingListCandidates: (listId: number, limit = 50) =>
      client.get<CBLReadingListCandidatesResponse>(
        `/v1/issue-identity/reading-lists/${listId}/cbl-candidates`,
        { params: { limit } },
      ),
    preview: (listId: number) =>
      client.get<CBLAdoptionPreview>(`/v1/issue-identity/cbl/${listId}/adoption-preview`),
    plan: (listId: number, choices: CBLAdoptionPlanChoices) =>
      client.post<CBLAdoptionPreview>(`/v1/issue-identity/cbl/${listId}/adoption-plan`, choices),
    commit: (
      listId: number,
      planId: number,
      preview: CBLAdoptionPreview,
      choices: CBLAdoptionPlanChoices,
    ) =>
      client.post<CBLAdoptionCommitResult>(
        `/v1/cbl/${listId}/reading-plans/${planId}/adoption-commit`,
        commitPayload(preview, choices),
      ),
    /**
     * One-decision adoption: adopt the source into a Reading Plan, creating the
     * plan from the source when it has none yet. This is the "Add this reading
     * order" action for the CBL browser.
     */
    commitNew: (
      listId: number,
      preview: CBLAdoptionPreview,
      choices: CBLAdoptionPlanChoices,
    ) =>
      client.post<CBLAdoptionCommitResult>(
        `/v1/cbl/${listId}/adoption-commit`,
        commitPayload(preview, choices),
        { timeout: 60_000 },
      ),
  }
}

export const cblSourcesApi = createCblSourcesApi(defaultHttpClient())
