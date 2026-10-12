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

  it('explains each unresolved identity status', () => {
    expect(
      identityResolutionReason(entry({ resolution_status: 'comicvine_identity_not_known' })),
    ).toBe('ComicVine has not confirmed this issue identity yet.')
    expect(
      identityResolutionReason(
        entry({ resolution_status: 'ambiguous_title_number_multiple_matches' }),
      ),
    ).toBe('Multiple owned comics match this title and issue number.')
    expect(
      identityResolutionReason(
        entry({ resolution_status: 'ambiguous_title_number_unverifiable_series' }),
      ),
    ).toBe('The title and issue number match is unverifiable for this series.')
    expect(
      identityResolutionReason(
        entry({ resolution_status: 'resolved_via_comicvine_canonical_ambiguous' }),
      ),
    ).toBe('This ComicVine identity maps to more than one owned comic.')
  })

  it('explains duplicate identities and generic fallbacks', () => {
    expect(
      identityResolutionReason(
        entry({
          resolution_status: 'no_owned_issue_for_comicvine_id',
          is_duplicate_identity: true,
        }),
      ),
    ).toBe('This ComicVine identity is already mapped to more than one comic.')
    expect(
      identityResolutionReason(
        entry({
          resolution_status: 'no_owned_issue_for_comicvine_id',
          comicvine_issue_id: '4000-99',
        }),
      ),
    ).toBe('Needs identity resolution for ComicVine issue 4000-99.')
    expect(
      identityResolutionReason(entry({ resolution_status: 'no_owned_issue_for_comicvine_id' })),
    ).toBe('ComicPile could not uniquely identify this comic.')
  })

  it('still explains an ambiguous class even when the decision is not unresolved', () => {
    expect(
      identityResolutionReason(
        entry({
          adoption_decision: 'excluded',
          adoption_class: 'ambiguous_unresolved',
        }),
      ),
    ).toBe('This entry has no ComicVine issue ID, so ComicPile cannot match it to an owned comic.')
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
