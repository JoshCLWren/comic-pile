import { defaultHttpClient, type HttpClient } from './httpClient'

/**
 * Preview classification vocabulary reported by the series-mapping surface.
 *
 * `safe_exact_match` is the only classification a caller may bulk-approve; every
 * other value stays needs-review or is reported as context.
 */
export type SeriesMappingClassification =
  | 'already_confirmed'
  | 'safe_exact_match'
  | 'needs_review_ambiguous'
  | 'needs_review_conflict'
  | 'unresolved'
  | 'excluded_special'

/** The one preview classification that may be bulk-confirmed. */
export const BULK_SAFE_SERIES_MAPPING_CLASSIFICATION = 'safe_exact_match'

export interface SeriesMappingPreviewScope {
  status: 'available' | 'unavailable'
  scope_key: string | null
  origin_issue_id: number
  series_label: string | null
  basis: string | null
}

export interface SeriesMappingPreviewCounts {
  already_confirmed: number
  safe_exact_match: number
  needs_review_ambiguous: number
  needs_review_conflict: number
  unresolved: number
  excluded_special: number
}

export interface SeriesMappingPreviewProviderSeries {
  id: string
  name: string
  publisher: string | null
  start_year: number | null
  count_of_issues: number | null
  site_detail_url: string | null
  image: Record<string, string> | null
}

export interface SeriesMappingPreviewRow {
  row_id: string
  issue_id: number
  issue_number: string
  title: string | null
  classification: SeriesMappingClassification
  thread_id: number | null
  thread_title: string | null
  current_mapping_status: string | null
  proposed_mapping: boolean
  default_selected: boolean
  reason: string | null
}

export interface SeriesMappingPreviewResponse {
  preview_token: string | null
  scope: SeriesMappingPreviewScope
  provider_series: SeriesMappingPreviewProviderSeries | null
  counts: SeriesMappingPreviewCounts
  rows: SeriesMappingPreviewRow[]
  issued_at: number
  expires_at: number | null
}

export interface SeriesMappingPreviewRequest {
  origin_issue_id: number
  provider: string
  provider_series_external_id: string
}

export interface SeriesMappingCommitRequest {
  preview_token: string
  idempotency_key: string
  approved_row_ids: string[]
}

export interface SeriesMappingCommitSeriesMapping {
  provider: string
  external_id: string
  status: string
  evidence_source: string
}

export interface SeriesMappingCommitResponse {
  idempotency_key: string
  confirmed_issue_ids: number[]
  already_confirmed_issue_ids: number[]
  needs_review_issue_ids: number[]
  hydration_queued_issue_ids: number[]
  series_mapping: SeriesMappingCommitSeriesMapping
}

/**
 * A preview row that reports a locally owned ComicPile issue.
 *
 * Rows without a `thread_id` are provider inventory for the selected volume; they
 * describe issues the reader does not own and can never be bulk-confirmed.
 */
export function isOwnedSeriesMappingRow(row: SeriesMappingPreviewRow): boolean {
  return row.thread_id !== null
}

/**
 * Return the rows a caller may bulk-approve for this preview.
 *
 * Only rows the preview classified `safe_exact_match` that also belong to an owned
 * issue qualify, so provider inventory rows never reach the commit surface.
 */
export function bulkApprovableSeriesMappingRows(
  rows: SeriesMappingPreviewRow[],
): SeriesMappingPreviewRow[] {
  return rows.filter(
    (row) =>
      row.classification === BULK_SAFE_SERIES_MAPPING_CLASSIFICATION && isOwnedSeriesMappingRow(row),
  )
}

/**
 * Build the series-mapping service bound to an HTTP client.
 *
 * @param client - HTTP transport used for every request.
 * @returns The series-mapping service bound to `client`.
 */
export function createSeriesMappingApi(client: HttpClient) {
  return {
    preview: (request: SeriesMappingPreviewRequest) =>
      client.post<SeriesMappingPreviewResponse>('/v1/catalog/series-mappings/preview', request),
    commit: (request: SeriesMappingCommitRequest) =>
      client.post<SeriesMappingCommitResponse>('/v1/catalog/series-mappings/commit', request),
  }
}

export const seriesMappingApi = createSeriesMappingApi(defaultHttpClient())