import type { ComicVineMappingHealth, ComicVineMappingStatus } from '../types/comic-vine';

export function getMappingStatus(mapping: ComicVineMappingHealth | null): ComicVineMappingStatus | null {
  if (!mapping) return null;
  return mapping.status;
}

export function getMappingStatusText(status: ComicVineMappingStatus | null): string {
  if (!status) return '';

  const statusMap: Record<ComicVineMappingStatus, string> = {
    not_applicable: 'Not applicable',
    fully_mapped: 'Fully mapped',
    partial: 'Partially mapped',
    unresolved: 'Needs mapping',
    needs_review: 'Needs review',
  };

  return statusMap[status];
}

export function getMappingStatusDescription(mapping: ComicVineMappingHealth | null): string {
  if (!mapping) return '';

  switch (mapping.status) {
    case 'not_applicable':
      return 'This series does not use issue tracking';
    case 'fully_mapped':
      return `${mapping.tracked_issue_count} issues mapped`;
    case 'partial':
      return `${mapping.confirmed_issue_count} of ${mapping.tracked_issue_count} issues mapped`;
    case 'unresolved':
      return `${mapping.tracked_issue_count} issues need mapping`;
    case 'needs_review':
      return `${mapping.needs_review_count} issues need review`;
    default:
      return '';
  }
}

export function needsMappingAttention(mapping: ComicVineMappingHealth | null): boolean {
  if (!mapping) return false;

  return mapping.status === 'partial' ||
         mapping.status === 'unresolved' ||
         mapping.status === 'needs_review';
}

export function hasConfirmedMappings(mapping: ComicVineMappingHealth | null): boolean {
  if (!mapping) return false;

  return mapping.confirmed_issue_count > 0;
}

export function getMappingSummary(mapping: ComicVineMappingHealth | null): string {
  if (!mapping) return '';

  switch (mapping.status) {
    case 'not_applicable':
      return 'No mapping needed';
    case 'fully_mapped':
      return 'All issues mapped';
    case 'partial':
      return `${mapping.confirmed_issue_count}/${mapping.tracked_issue_count} mapped`;
    case 'unresolved':
      return `${mapping.needs_mapping_count} need mapping`;
    case 'needs_review':
      return `${mapping.needs_review_count} need review`;
    default:
      return '';
  }
}
