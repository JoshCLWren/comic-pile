import { describe, expect, it } from 'vitest'
import {
  bulkApprovableSeriesMappingRows,
  createSeriesMappingApi,
  isOwnedSeriesMappingRow,
  type SeriesMappingPreviewRow,
} from '../services/api-series-mapping'
import { createHttpClientStub } from './httpClientStub'

const previewRequest = {
  origin_issue_id: 42,
  provider: 'comicvine',
  provider_series_external_id: '4050-1',
}

describe('seriesMappingApi.preview', () => {
  it('posts the stateless preview to the canonical v2 custom method (#5716)', async () => {
    const client = createHttpClientStub()
    client.post.mockResolvedValueOnce({
      preview_token: 'signed-token',
      scope: { status: 'available', scope_key: 'exact:42:1', origin_issue_id: 42, series_label: null, basis: null },
      provider_series: null,
      counts: {
        already_confirmed: 0,
        safe_exact_match: 1,
        needs_review_ambiguous: 0,
        needs_review_conflict: 0,
        unresolved: 1,
        excluded_special: 0,
      },
      rows: [],
      issued_at: 1,
      expires_at: 601,
    })

    const api = createSeriesMappingApi(client)
    const result = await api.preview(previewRequest)

    expect(client.post).toHaveBeenCalledTimes(1)
    expect(client.post).toHaveBeenCalledWith('/v2/seriesMappings:preview', previewRequest)
    expect(result.preview_token).toBe('signed-token')
  })

  it('sends the scope mode untouched so queue and sibling previews keep their semantics', async () => {
    const client = createHttpClientStub()
    const request = { ...previewRequest, scope_mode: 'queue_thread_bootstrap' as const }
    client.post.mockResolvedValueOnce({ rows: [] })

    await createSeriesMappingApi(client).preview(request)

    expect(client.post).toHaveBeenCalledWith('/v2/seriesMappings:preview', request)
  })
})

describe('seriesMappingApi.commit', () => {
  it('keeps the durable v2 commit as the only writing operation (#5716)', async () => {
    const client = createHttpClientStub()
    const request = {
      preview_token: 'signed-token',
      idempotency_key: 'key-1',
      approved_row_ids: ['issue:42'],
    }
    client.post.mockResolvedValueOnce({ confirmed_issue_ids: [42] })

    const api = createSeriesMappingApi(client)
    await api.commit(request)

    expect(client.post).toHaveBeenCalledTimes(1)
    expect(client.post).toHaveBeenCalledWith('/v2/series-mapping-commits', request)
  })
})

describe('owned row approval boundary', () => {
  const row = (overrides: Partial<SeriesMappingPreviewRow> = {}): SeriesMappingPreviewRow => ({
    row_id: 'issue:42',
    issue_id: 42,
    issue_number: '1',
    title: null,
    classification: 'safe_exact_match',
    thread_id: 7,
    thread_title: 'Series',
    current_mapping_status: null,
    proposed_mapping: true,
    default_selected: true,
    metadata_refresh_required: false,
    reason: null,
    ...overrides,
  })

  it('rejects provider-only rows from the bulk approval set', () => {
    const providerOnly = row({
      row_id: 'roster:99',
      issue_id: 99,
      classification: 'unresolved',
      thread_id: null,
      default_selected: false,
      proposed_mapping: false,
    })

    expect(isOwnedSeriesMappingRow(providerOnly)).toBe(false)
    expect(bulkApprovableSeriesMappingRows([providerOnly])).toEqual([])
    expect(bulkApprovableSeriesMappingRows([row(), providerOnly])).toEqual([row()])
  })
})
