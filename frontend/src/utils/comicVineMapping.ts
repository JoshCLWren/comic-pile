import type { ComicVineMappingHealth } from '../types/comic-vine'

/**
 * Compact, count-bearing label for the queue mapping-health indicator.
 *
 * The label states both the count and the state in text so the queue never
 * communicates mapping health through color alone.
 */
export function getMappingHealthLabel(mapping: ComicVineMappingHealth): string {
  switch (mapping.status) {
    case 'not_applicable':
      return 'Not applicable'
    case 'fully_mapped':
      return 'Fully mapped'
    case 'partial':
      return `${mapping.confirmed_issue_count} of ${mapping.tracked_issue_count} mapped`
    case 'unresolved':
      return `${mapping.needs_mapping_count} need mapping`
    case 'needs_review':
      return `${mapping.needs_review_count} need review`
  }
}

/**
 * Longer explanation for the mapping-health indicator tooltip and assistive
 * technology. Ambiguous, conflicting, and review-needed identities are
 * described as review work rather than as ordinary missing mappings.
 */
export function getMappingHealthDescription(mapping: ComicVineMappingHealth): string {
  switch (mapping.status) {
    case 'not_applicable':
      return 'This series does not track ComicVine issue identity.'
    case 'fully_mapped':
      return `All ${mapping.tracked_issue_count} issues are confirmed against ComicVine.`
    case 'partial':
      return `${mapping.confirmed_issue_count} of ${mapping.tracked_issue_count} issues are confirmed; ${mapping.needs_mapping_count} still need mapping.`
    case 'unresolved':
      return `${mapping.needs_mapping_count} of ${mapping.tracked_issue_count} issues have no confirmed ComicVine identity.`
    case 'needs_review':
      return `${mapping.needs_review_count} issues are ambiguous or conflicting and need review before they can be mapped.`
  }
}

/**
 * True when a series still needs the user to repair its ComicVine identity.
 *
 * Fully mapped series and series without ComicVine issue tracking stay quiet so
 * mapped rows never carry mapping chrome.
 */
export function needsMappingAttention(mapping: ComicVineMappingHealth | null | undefined): boolean {
  if (!mapping) return false

  return (
    mapping.status === 'partial' ||
    mapping.status === 'unresolved' ||
    mapping.status === 'needs_review'
  )
}
