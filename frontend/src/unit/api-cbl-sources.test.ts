import { beforeEach, describe, expect, it, vi } from 'vitest'

import type {
  CBLAdoptionPreview,
  CBLAdoptionPreviewEntry,
} from '../services/api-cbl-sources'

const api = vi.hoisted(() => ({ post: vi.fn() }))

vi.mock('../services/api', () => ({ default: api }))

import { cblSourcesApi } from '../services/api-cbl-sources'

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

describe('cblSourcesApi.commit', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.post.mockResolvedValue({
      id: 77,
      reused_positions: [1],
      created_positions: [2],
      excluded_positions: [3],
      unresolved_positions: [4],
    })
  })

  it('targets the selected Reading Plan and maps reviewed missing entries', async () => {
    const result = await cblSourcesApi.commit(42, 77, reviewedPreview, {
      series_decisions: {},
      entry_decisions: { '102': true, '103': false },
    })

    expect(result).toEqual({
      id: 77,
      reused_positions: [1],
      created_positions: [2],
      excluded_positions: [3],
      unresolved_positions: [4],
    })
    expect(api.post).toHaveBeenCalledWith(
      '/v1/cbl/42/reading-plans/77/adoption-commit',
      {
        entry_decisions: { 2: 'include', 3: 'exclude' },
        series_decisions: [],
        series_overrides: [],
        content_hash: 'hash-42',
        revision_sha: 'abcdef1234567890',
      },
    )
  })
})
