import type { CBLAdoptionPreviewEntry } from '../services/api-cbl-sources'

/**
 * Explain why one CBL entry still needs identity resolution.
 *
 * @param entry - Preview row flagged as unresolved or ambiguous.
 * @returns A reader-facing reason, or null when the entry does not need resolution.
 */
export function identityResolutionReason(entry: CBLAdoptionPreviewEntry): string | null {
  if (entry.adoption_decision !== 'unresolved' && entry.adoption_class !== 'ambiguous_unresolved') {
    return null
  }
  switch (entry.resolution_status) {
    case 'ambiguous_no_comicvine_id':
      return 'This entry has no ComicVine issue ID, so ComicPile cannot match it to an owned comic.'
    case 'comicvine_identity_not_known':
      return 'ComicVine has not confirmed this issue identity yet.'
    case 'ambiguous_title_number_multiple_matches':
      return 'Multiple owned comics match this title and issue number.'
    case 'ambiguous_title_number_unverifiable_series':
      return 'The title and issue number match is unverifiable for this series.'
    case 'resolved_via_comicvine_canonical_ambiguous':
      return 'This ComicVine identity maps to more than one owned comic.'
    default:
      if (entry.is_duplicate_identity) {
        return 'This ComicVine identity is already mapped to more than one comic.'
      }
      return entry.comicvine_issue_id
        ? `Needs identity resolution for ComicVine issue ${entry.comicvine_issue_id}.`
        : 'ComicPile could not uniquely identify this comic.'
  }
}
