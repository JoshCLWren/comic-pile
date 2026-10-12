import { describe, expect, it } from 'vitest'
import { identityResolutionReason } from '../utils/cblResolutionReason'
import type { CBLAdoptionPreviewEntry } from '../services/api-cbl-sources'

function entry(overrides: Partial<CBLAdoptionPreviewEntry>): CBLAdoptionPreviewEntry {
  return {
    cbl_position: 1,
    cbl_entry_id: 101,
    series_name: 'Ultimate Spider-Man',
    issue_number: '1',
    series_group_id: 'group-1',
    adoption_class: 'ambiguous_unresolved',
    adoption_decision: 'unresolved',
    adopted: false,
    comicvine_issue_id: null,
    comicvine_series_id: null,
    series_provider: null,
    series_external_id: null,
    resolved_issue_id: null,
    canonical_issue_id: null,
    read_status: null,
    read_at: null,
    resolution_status: 'ambiguous_no_comicvine_id',
    is_duplicate_identity: false,
    ...overrides,
  }
}

describe('identityResolutionReason', () => {
  it('explains a missing ComicVine issue id', () => {
    expect(identityResolutionReason(entry({}))).toBe(
      'This entry has no ComicVine issue ID, so ComicPile cannot match it to an owned comic.',
    )
  })

  it('is silent for resolved existing comics', () => {
    expect(
      identityResolutionReason(
        entry({
          adoption_class: 'existing',
          adoption_decision: 'included_existing',
          resolution_status: 'resolved_via_comicvine_canonical',
        }),
      ),
    ).toBeNull()
  })
})
