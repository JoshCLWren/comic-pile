import { describe, expect, it } from 'vitest'
import { applyCblAdoptionChoices } from '../utils/cblAdoptionPlan'
import type { CBLAdoptionPreview, CBLAdoptionPreviewEntry } from '../services/api-cbl-sources'

function entry(overrides: Partial<CBLAdoptionPreviewEntry>): CBLAdoptionPreviewEntry {
  return {
    cbl_position: 1,
    cbl_entry_id: 101,
    series_name: 'Ultimate Spider-Man',
    issue_number: '1',
    series_group_id: 'group-1',
    adoption_class: 'existing',
    adoption_decision: 'included_existing',
    adopted: true,
    comicvine_issue_id: '4000-1',
    comicvine_series_id: null,
    series_provider: 'comicvine',
    series_external_id: null,
    resolved_issue_id: 11,
    canonical_issue_id: 11,
    read_status: 'unread',
    read_at: null,
    resolution_status: 'resolved_via_comicvine_canonical',
    is_duplicate_identity: false,
    ...overrides,
  }
}

const preview: CBLAdoptionPreview = {
  source: {
    source_list_id: 7,
    source_repository: 'JoshCLWren/CBL-ReadingLists',
    source_path: 'Ultimate.cbl',
    content_hash: 'hash-1',
    revision_sha: 'abcdef1234567890',
  },
  total_positions: 2,
  entries: [
    entry({}),
    entry({
      cbl_position: 2,
      cbl_entry_id: 102,
      issue_number: '2',
      adoption_class: 'missing_importable',
      adoption_decision: 'would_create_missing',
      resolved_issue_id: null,
      canonical_issue_id: null,
      resolution_status: 'no_owned_issue_for_comicvine_id',
    }),
  ],
  summary: {
    reused_existing_count: 1,
    missing_would_create_count: 1,
    excluded_count: 0,
    unresolved_count: 0,
    awaiting_opt_in_count: 0,
    final_adopted_count: 2,
    final_adopted_order: [1, 2],
    reused_existing_positions: [1],
    missing_would_create_positions: [2],
    excluded_positions: [],
    unresolved_positions: [],
    awaiting_opt_in_positions: [],
  },
}

describe('applyCblAdoptionChoices', () => {
  it('excludes a series locally without changing the original preview', () => {
    const next = applyCblAdoptionChoices(preview, { 'group-1': false }, {})
    expect(next.summary.final_adopted_count).toBe(0)
    expect(next.summary.excluded_count).toBe(2)
    expect(next.entries.every((item) => item.adoption_decision === 'excluded')).toBe(true)
    expect(preview.summary.final_adopted_count).toBe(2)
  })

  it('lets an entry decision override a series exclude', () => {
    const next = applyCblAdoptionChoices(preview, { 'group-1': false }, { '101': true })
    expect(next.entries[0]?.adopted).toBe(true)
    expect(next.entries[1]?.adopted).toBe(false)
    expect(next.summary.reused_existing_count).toBe(1)
    expect(next.summary.excluded_count).toBe(1)
  })

  it('excludes one owned entry individually without dropping the missing issue', () => {
    const next = applyCblAdoptionChoices(preview, {}, { '101': false })
    expect(next.entries[0]?.adoption_decision).toBe('excluded')
    expect(next.entries[0]?.adopted).toBe(false)
    expect(next.entries[1]?.adopted).toBe(true)
    expect(next.summary.reused_existing_count).toBe(0)
    expect(next.summary.missing_would_create_count).toBe(1)
    expect(next.summary.excluded_positions).toEqual([1])
  })

  it('lets an unresolved entry be skipped without guessing identity', () => {
    const unresolvedPreview: CBLAdoptionPreview = {
      ...preview,
      entries: [
        entry({
          adoption_class: 'ambiguous_unresolved',
          adoption_decision: 'unresolved',
          adopted: false,
          resolved_issue_id: null,
          canonical_issue_id: null,
        }),
      ],
    }
    const skipped = applyCblAdoptionChoices(unresolvedPreview, {}, { '101': false })
    expect(skipped.entries[0]?.adoption_decision).toBe('excluded')
    expect(skipped.summary.excluded_positions).toEqual([1])
    const left = applyCblAdoptionChoices(unresolvedPreview, {}, {})
    expect(left.entries[0]?.adoption_decision).toBe('unresolved')
    expect(left.summary.unresolved_positions).toEqual([1])
  })

  it('treats missing issues with no explicit choice as awaiting opt-in', () => {
    const awaitingPreview: CBLAdoptionPreview = {
      ...preview,
      entries: [
        entry({
          cbl_entry_id: 102,
          adoption_class: 'missing_importable',
          adoption_decision: 'awaiting_opt_in',
          adopted: false,
          resolved_issue_id: null,
          canonical_issue_id: null,
        }),
      ],
    }
    const next = applyCblAdoptionChoices(awaitingPreview, {}, {})
    expect(next.entries[0]?.adoption_decision).toBe('would_create_missing')
    const none = applyCblAdoptionChoices(
      {
        ...awaitingPreview,
        entries: [
          entry({
            cbl_entry_id: 102,
            adoption_class: 'missing_importable',
            adoption_decision: 'awaiting_opt_in',
            adopted: false,
            resolved_issue_id: null,
            canonical_issue_id: null,
          }),
        ],
      },
      { 'group-1': false },
      {},
    )
    expect(none.entries[0]?.adoption_decision).toBe('excluded')
  })
})
