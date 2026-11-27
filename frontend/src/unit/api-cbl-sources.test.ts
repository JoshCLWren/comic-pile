import { beforeEach, describe, expect, it } from 'vitest'

import { createCblSourcesApi } from '../services/api-cbl-sources'
import type {
  CBLAdoptionPreview,
  CBLAdoptionPreviewEntry,
} from '../services/api-cbl-sources'
import { createHttpClientStub } from './httpClientStub'

const client = createHttpClientStub()
const cblSourcesApi = createCblSourcesApi(client)

function entry(overrides: Partial<CBLAdoptionPreviewEntry>): CBLAdoptionPreviewEntry {
  return {
    cbl_position: 1,
    cbl_entry_id: 101,
    series_name: 'B.P.R.D.',
    issue_number: '1',
    series_group_id: 'bprd',
    adoption_class: 'existing',
    adoption_decision: 'included_existing',
    adopted: false,
    comicvine_issue_id: 'cv-1',
    comicvine_series_id: 'series-1',
    series_provider: 'comicvine',
    series_external_id: 'series-1',
    resolved_issue_id: 1,
    canonical_issue_id: 1,
    read_status: 'unread',
    read_at: null,
    resolution_status: 'resolved',
    is_duplicate_identity: false,
    ...overrides,
  }
}

// SAFETY: the preview fixture supplies only the fields the source list reads
const reviewedPreview = {
  source: {
    source_list_id: 42,
    source_repository: 'example/cbl',
    source_path: 'Dark Horse/BPRD/Plague of Frogs.cbl',
    content_hash: 'hash-42',
    revision_sha: 'abcdef1234567890',
  },
  entries: [
    entry({ cbl_position: 1, adoption_class: 'existing', adopted: true }),
    entry({
      cbl_position: 2,
      cbl_entry_id: 102,
      adoption_class: 'missing_importable',
      adoption_decision: 'would_create_missing',
      adopted: true,
    }),
    entry({
      cbl_position: 3,
      cbl_entry_id: 103,
      adoption_class: 'missing_importable',
      adoption_decision: 'excluded',
      adopted: false,
    }),
    entry({
      cbl_position: 4,
      cbl_entry_id: 104,
      adoption_class: 'ambiguous_unresolved',
      adoption_decision: 'unresolved',
      adopted: false,
    }),
  ],
} as CBLAdoptionPreview

describe('cblSourcesApi canonical v2 catalog reads (#5712)', () => {
  beforeEach(() => {
    client.get.mockReset()
  })

  it('discovers sources through the canonical List collection and unwraps items', async () => {
    const items = [
      {
        id: 7,
        name: 'JLI',
        source_path: 'DC/JLI/JLI.cbl',
        source_repository: 'JoshCLWren/CBL-ReadingLists',
        declared_issue_count: 10,
        content_hash: 'h-jli',
        revision_sha: 'rev-1',
      },
    ]
    client.get.mockResolvedValue({ items, total: 1, catalog_total: 1 })

    await expect(cblSourcesApi.discover('  JLI  ', 10)).resolves.toEqual(items)
    expect(client.get).toHaveBeenCalledWith('/v2/cblSources', {
      params: { filter: 'q:JLI', order_by: 'name', page_size: 10 },
    })
  })

  it('encodes folder browse positions as opaque page tokens, never a page parameter', async () => {
    client.get.mockResolvedValue({ items: [], folders: [], total: 0 })

    await cblSourcesApi.browse({ folder: 'DC/Marvel', page: 3, pageSize: 25 })
    const [path, config] = client.get.mock.calls[0] as [string, { params: Record<string, unknown> }]
    expect(path).toBe('/v2/cblSources')
    expect(config.params.filter).toBe('folder:DC/Marvel')
    expect(config.params.order_by).toBe('name')
    expect(config.params.page_size).toBe(25)
    expect(config.params.page).toBeUndefined()
    const token = String(config.params.page_token)
    expect(token).not.toContain('=')
    expect(atob(token)).toBe(JSON.stringify({ p: 3, f: 'folder:DC/Marvel', o: 'name', s: 25 }))
  })

  it('turns a search query into a catalog-wide filter and ignores folder scope', async () => {
    client.get.mockResolvedValue({ items: [], folders: [], total: 0 })

    await cblSourcesApi.browse({ folder: 'DC', query: '  Secret Wars ', page: 1 })
    const [, config] = client.get.mock.calls[0] as [string, { params: Record<string, unknown> }]
    expect(config.params.filter).toBe('q:Secret Wars')
    expect(config.params.page_token).toBeUndefined()
  })

  it('reads detail and exact occurrences from the canonical v2 resources', async () => {
    client.get.mockResolvedValue({ id: 42 })
    await cblSourcesApi.detail(42, { offset: 10, limit: 100 })
    expect(client.get).toHaveBeenCalledWith('/v2/cblSources/42', {
      params: { offset: 10, limit: 100 },
    })

    client.get.mockResolvedValue({ occurrences: [] })
    await cblSourcesApi.findByComicvineIssue('4000-123', { limit: 25 })
    expect(client.get).toHaveBeenCalledWith('/v2/cblOccurrences', {
      params: { filter: 'comicvine_issue_id:4000-123', limit: 25 },
    })
  })
})

describe('cblSourcesApi.commit', () => {
  beforeEach(() => {
    client.post.mockReset()
    client.post.mockResolvedValue({
      id: 77,
      reused_positions: [1],
      created_positions: [2],
      excluded_positions: [3],
      unresolved_positions: [4],
    })
  })

  it('targets the selected Reading Plan and maps series choices plus entry overrides', async () => {
    const result = await cblSourcesApi.commit(42, 77, reviewedPreview, {
      series_decisions: { bprd: false },
      entry_decisions: { '102': true, '103': false },
    })

    expect(result).toEqual({
      id: 77,
      reused_positions: [1],
      created_positions: [2],
      excluded_positions: [3],
      unresolved_positions: [4],
    })
    expect(client.post).toHaveBeenCalledWith(
      '/v2/reading-lists/42/reading-plans/77/adoption-commits',
      {
        entry_decisions: {},
        series_decisions: [],
        series_overrides: [
          { cbl_position: 1, decision: 'exclude' },
          { cbl_position: 2, decision: 'include' },
          { cbl_position: 3, decision: 'exclude' },
          { cbl_position: 4, decision: 'exclude' },
        ],
        overlap_decisions: [],
        content_hash: 'hash-42',
        revision_sha: 'abcdef1234567890',
      },
      { timeout: 60_000 },
    )
  })

  it('carries the reader-approved series overlap decisions into the commit (#4020)', async () => {
    await cblSourcesApi.commit(42, 77, reviewedPreview, {
      series_decisions: {},
      entry_decisions: {},
      overlap_decisions: [{ overlap_id: 'mister-miracle|jli', choice: 'continue_series' }],
    })

    expect(client.post).toHaveBeenCalledWith(
      '/v2/reading-lists/42/reading-plans/77/adoption-commits',
      expect.objectContaining({
        overlap_decisions: [{ overlap_id: 'mister-miracle|jli', choice: 'continue_series' }],
      }),
      { timeout: 60_000 },
    )
  })

  it('expands colliding series_name groups into distinct position overrides', async () => {
    // SAFETY: the colliding-preview fixture supplies only the fields the dedupe check reads
    const collidingPreview = {
      ...reviewedPreview,
      entries: [
        entry({
          cbl_position: 1,
          cbl_entry_id: 201,
          series_name: 'Shared Title',
          series_group_id: 'shared-2001',
        }),
        entry({
          cbl_position: 2,
          cbl_entry_id: 202,
          series_name: 'Shared Title',
          series_group_id: 'shared-2010',
        }),
      ],
    } as CBLAdoptionPreview

    await cblSourcesApi.commit(42, 77, collidingPreview, {
      series_decisions: { 'shared-2001': true, 'shared-2010': false },
      entry_decisions: {},
    })

    expect(client.post).toHaveBeenCalledWith(
      '/v2/reading-lists/42/reading-plans/77/adoption-commits',
      expect.objectContaining({
        series_decisions: [],
        series_overrides: [
          { cbl_position: 1, decision: 'include' },
          { cbl_position: 2, decision: 'exclude' },
        ],
      }),
      { timeout: 60_000 },
    )
  })
})

describe('cblSourcesApi.commitNew', () => {
  beforeEach(() => {
    client.post.mockReset()
    client.post.mockResolvedValue({
      id: 78,
      name: 'Dark Horse/BPRD/Plague of Frogs.cbl',
      reused_positions: [1],
      created_positions: [2],
      excluded_positions: [3],
      unresolved_positions: [4],
    })
  })

  it('posts to the plan-creating adoption route with the same override payload', async () => {
    const result = await cblSourcesApi.commitNew(42, reviewedPreview, {
      series_decisions: { bprd: false },
      entry_decisions: { '102': true },
    })

    expect(result).toEqual({
      id: 78,
      name: 'Dark Horse/BPRD/Plague of Frogs.cbl',
      reused_positions: [1],
      created_positions: [2],
      excluded_positions: [3],
      unresolved_positions: [4],
    })
    expect(client.post).toHaveBeenCalledWith(
      '/v2/reading-lists/42/adoption-commits',
      {
        entry_decisions: {},
        series_decisions: [],
        series_overrides: [
          { cbl_position: 1, decision: 'exclude' },
          { cbl_position: 2, decision: 'include' },
          { cbl_position: 3, decision: 'exclude' },
          { cbl_position: 4, decision: 'exclude' },
        ],
        overlap_decisions: [],
        content_hash: 'hash-42',
        revision_sha: 'abcdef1234567890',
      },
      { timeout: 60_000 },
    )
  })
})
