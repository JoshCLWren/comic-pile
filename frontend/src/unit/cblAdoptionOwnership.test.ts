import { beforeEach, describe, expect, it } from 'vitest'
import type { CBLAdoptionPreview } from '../services/api-cbl-sources'
import {
  canonicalListId,
  forgetOwnedCblList,
  readOwnedCblList,
  restoreCommittedChoices,
  restoreOverlapChoices,
  saveOwnedCblList,
} from '../utils/cblAdoptionOwnership'

const preview = {
  source: {
    source_list_id: 7,
    source_repository: 'shared/cbls',
    source_path: 'Ultimate.cbl',
    content_hash: 'hash-1',
    revision_sha: 'rev-1',
  },
  total_positions: 3,
  entries: [
    {
      cbl_position: 1,
      cbl_entry_id: 101,
      series_name: 'Ultimate Spider-Man',
      issue_number: '1',
      series_group_id: 'volume-2001',
      adoption_class: 'existing',
      adoption_decision: 'included_existing',
      adopted: true,
      comicvine_issue_id: '4000-1',
      comicvine_series_id: '4000',
      series_provider: 'comicvine',
      series_external_id: '4000',
      resolved_issue_id: 11,
      canonical_issue_id: 11,
      volume_year: null,
      publication_year: null,
      read_status: 'unread',
      read_at: null,
      resolution_status: 'resolved',
      is_duplicate_identity: false,
    },
    {
      cbl_position: 2,
      cbl_entry_id: 102,
      series_name: 'Ultimate Spider-Man',
      issue_number: '2',
      series_group_id: 'volume-2001',
      adoption_class: 'existing',
      adoption_decision: 'included_existing',
      adopted: true,
      comicvine_issue_id: '4000-2',
      comicvine_series_id: '4000',
      series_provider: 'comicvine',
      series_external_id: '4000',
      resolved_issue_id: 12,
      canonical_issue_id: 12,
      volume_year: null,
      publication_year: null,
      read_status: 'read',
      read_at: '2026-11-20T00:00:00Z',
      resolution_status: 'resolved',
      is_duplicate_identity: false,
    },
    {
      cbl_position: 3,
      cbl_entry_id: 103,
      series_name: 'Another Series',
      issue_number: '1',
      series_group_id: 'volume-2010',
      adoption_class: 'existing',
      adoption_decision: 'included_existing',
      adopted: true,
      comicvine_issue_id: '5000-1',
      comicvine_series_id: '5000',
      series_provider: 'comicvine',
      series_external_id: '5000',
      resolved_issue_id: 13,
      canonical_issue_id: 13,
      volume_year: null,
      publication_year: null,
      read_status: 'unread',
      read_at: null,
      resolution_status: 'resolved',
      is_duplicate_identity: false,
    },
  ],
  summary: {
    reused_existing_count: 3,
    missing_would_create_count: 0,
    excluded_count: 0,
    unresolved_count: 0,
    awaiting_opt_in_count: 0,
    final_adopted_count: 3,
    final_adopted_order: [1, 2, 3],
    reused_existing_positions: [1, 2, 3],
    missing_would_create_positions: [],
    excluded_positions: [],
    unresolved_positions: [],
    awaiting_opt_in_positions: [],
  },
} as CBLAdoptionPreview

describe('cblAdoptionOwnership', () => {
  beforeEach(() => localStorage.clear())

  it('restores a whole-volume exclusion and a single rechecked issue', () => {
    const restored = restoreCommittedChoices(preview, {
      entry_decisions: { '101': 'include' },
      series_overrides: { '1': 'exclude', '2': 'exclude', '3': 'exclude' },
    })
    expect(restored).toEqual({
      series: { 'volume-2001': false, 'volume-2010': false },
      entries: { '101': true },
    })
  })

  it('does not turn one unchecked issue into a whole-volume exclusion', () => {
    const restored = restoreCommittedChoices(preview, {
      entry_decisions: { '101': 'exclude' },
      series_overrides: {},
    })
    expect(restored).toEqual({
      series: {},
      entries: { '101': false },
    })
  })

  it('records a uniform volume decision as a series choice', () => {
    const restored = restoreCommittedChoices(preview, {
      series_overrides: { '1': 'exclude', '2': 'exclude' },
    })
    expect(restored.series['volume-2001']).toBe(false)
    expect(restored.entries).toEqual({})
  })

  it('ignores malformed committed documents and invalid overlap answers', () => {
    expect(restoreCommittedChoices(preview, null)).toEqual({ series: {}, entries: {} })
    expect(restoreOverlapChoices([{ overlap_id: 'pair-1', choice: 'keep_both' }])).toEqual({})
    expect(restoreOverlapChoices([{ overlap_id: 'pair-1', choice: 'continue_series' }])).toEqual({
      'pair-1': 'continue_series',
    })
  })

  it('uses only the canonical list ID, never the compatibility plan ID', () => {
    expect(canonicalListId({ id: 42, custom_cbl_list_id: 900 } as never)).toBe(900)
    expect(canonicalListId({ id: 42 } as never)).toBeNull()
    expect(canonicalListId({ id: 42, custom_cbl_list_id: 0 } as never)).toBeNull()
  })

  it('stores a committed pointer by source and removes it on stale revision', () => {
    const link = {
      sourceId: 7,
      listId: 900,
      listVersion: 3,
      contentHash: 'hash-1',
      revisionSha: 'rev-1',
    }
    saveOwnedCblList(link)
    expect(readOwnedCblList(7)).toEqual(link)
    expect(readOwnedCblList(8)).toBeNull()
    forgetOwnedCblList(7)
    expect(readOwnedCblList(7)).toBeNull()
  })
})
