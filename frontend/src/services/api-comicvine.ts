import api from './api'

export interface ComicVineCreator {
  creator_id?: number | null
  name: string
  roles: string[]
}

export interface ComicVineComicPileMatch {
  issue_id: number
  thread_id: number
  thread_title: string
  issue_number: string
  status: 'read' | 'unread'
}

export interface ComicVineRelatedIssue {
  comicvine_issue_id: string
  series_name: string | null
  issue_number: string | null
  name: string | null
  cover_date: string | null
  comicvine_url: string | null
  comicpile_matches: ComicVineComicPileMatch[]
}

export interface ComicVineStoryArc {
  comicvine_arc_id: number
  name: string
  comicvine_url: string | null
  related_issues: ComicVineRelatedIssue[]
  total_related_count: number | null
}

export interface ComicVineImportIssuePayload {
  title: string
  comicvine_issue_id: number
  issue_number?: string | null
  reading_order_id?: number | null
  anchor_before_thread_id?: number | null
  anchor_after_thread_id?: number | null
}

export interface ComicVineImportIssueResult {
  thread_id: number
  issue_id: number
  external_identity_id: number
  reading_order_id: number | null
  position: number | null
  total_items: number | null
}

export interface ComicVineIssueIntelligence {
  comicvine_issue_id: string
  comicvine_url: string | null
  series_name: string | null
  series_id: number | null
  issue_number: string | null
  name: string | null
  description: string | null
  image_url: string | null
  cover_date: string | null
  store_date: string | null
  creators: ComicVineCreator[]
  story_arcs: ComicVineStoryArc[]
}

export interface ComicVineSeriesResult {
  comicvine_volume_id: number
  name: string
  publisher: string | null
  start_year: number | null
  issue_count: number | null
  site_detail_url: string | null
  image_url: string | null
}

export interface ComicVineSeriesSearchResponse {
  query: string
  results: ComicVineSeriesResult[]
  total_available: number | null
  offset: number
  limit: number
  has_more: boolean
  next_offset: number | null
}

export interface ComicVineResolvedIssue {
  comicvine_issue_id: number
  series_name: string | null
  volume_id: number | null
  issue_number: string | null
  name: string | null
  cover_date: string | null
  store_date: string | null
  image_url: string | null
  site_detail_url: string | null
}

export type ComicVineResolveKind = 'issue' | 'volume' | 'search'

export interface ComicVineResolveResponse {
  input: string
  kind: ComicVineResolveKind
  validation_error: string | null
  issue: ComicVineResolvedIssue | null
  volume: ComicVineSeriesResult | null
  issues: ComicVineIssueCandidate[]
}

export interface ComicVineIssueCandidate {
  comicvine_issue_id: number
  issue_number: string | null
  name: string | null
  cover_date: string | null
  store_date: string | null
  image_url: string | null
  site_detail_url: string | null
}

export interface ComicVineSeriesIssuesResponse {
  comicvine_volume_id: number
  series_name: string
  issues: ComicVineIssueCandidate[]
}

export interface IssueIdentityMapping {
  external_identity_id: number
  provider: string
  comicvine_id: string
  status: string
  confidence: number | null
  evidence_source: string | null
  created_at: string | null
}

export interface IssueIdentityResponse {
  issue_id: number
  thread_id: number
  thread_title: string
  has_confirmed_identity: boolean
  comicvine_issue_id: string | null
  confirmed_mappings: IssueIdentityMapping[]
  candidate_mappings: IssueIdentityMapping[]
  has_unresolved: boolean
}

export interface MetadataRefreshResponse {
  issue_id: number
  refreshed: boolean
  comicvine_issue_id: string | null
}

export interface CanonicalCorrection {
  id: number
  field_name: string
  provider_value: string | null
  canonical_value: string
  provenance: string
  created_by: number
  created_at: string
}

export interface MetadataCorrectionsResponse {
  issue_id: number
  corrections: CanonicalCorrection[]
}

export const comicVineApi = {
  getIssueIntelligence: (issueId: number) =>
    api.get<ComicVineIssueIntelligence | null>(`/v1/issues/${issueId}/comicvine`),
  importIssue: (payload: ComicVineImportIssuePayload) =>
    api.post<ComicVineImportIssueResult, ComicVineImportIssuePayload>('/v1/comicvine/issues:import', payload),
  searchSeries: (query: string, limit = 10, offset = 0) =>
    api.get<ComicVineSeriesSearchResponse>(`/v1/comicvine/search/series`, { params: { q: query, limit, offset } }),
  resolveIdentity: (input: string) =>
    api.get<ComicVineResolveResponse>(`/v1/comicvine/resolve`, { params: { input } }),
  getSeriesIssues: (volumeId: number, seriesName = '') =>
    api.get<ComicVineSeriesIssuesResponse>(`/v1/comicvine/series/${volumeId}/issues`, { params: { series_name: seriesName } }),
  getIssueIdentity: (issueId: number) =>
    api.get<IssueIdentityResponse>(`/v1/comicvine/issues/${issueId}/identity`),
  confirmIdentity: (issueId: number, comicvineIssueId: number) =>
    api.post<IssueIdentityResponse>(`/v1/comicvine/issues/${issueId}/identity:confirm`, { comicvine_issue_id: comicvineIssueId }),
  replaceIdentity: (issueId: number, comicvineIssueId: number, reason?: string) =>
    api.post<IssueIdentityResponse>(`/v1/comicvine/issues/${issueId}/identity:replace`, { comicvine_issue_id: comicvineIssueId, reason }),
  refreshMetadata: (issueId: number) =>
    api.post<MetadataRefreshResponse>(`/v1/comicvine/issues/${issueId}/metadata:refresh`),
  applyCorrection: (issueId: number, fieldName: string, canonicalValue: string, reason?: string) =>
    api.post<MetadataCorrectionsResponse>(`/v1/comicvine/issues/${issueId}/metadata:correct`, { field_name: fieldName, canonical_value: canonicalValue, reason }),
  listCorrections: (issueId: number) =>
    api.get<MetadataCorrectionsResponse>(`/v1/comicvine/issues/${issueId}/metadata:corrections`),
  revertCorrection: (issueId: number, correctionId: number) =>
    api.post<MetadataCorrectionsResponse>(`/v1/comicvine/issues/${issueId}/metadata:revert`, { correction_id: correctionId }),
  removeIdentity: (issueId: number) =>
    api.delete<IssueIdentityResponse>(`/v1/comicvine/issues/${issueId}/identity`),
}