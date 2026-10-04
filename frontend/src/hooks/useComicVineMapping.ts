import { useQuery } from '@tanstack/react-query';
import type { ThreadListItem } from '../types';
import type { ComicVineMappingHealth, ComicVineMappingStatus } from '../types/comic-vine';

/**
 * Hook to get ComicVine mapping health for a queue thread
 */
export function useComicVineMapping(thread: ThreadListItem | null) {
  return useQuery({
    queryKey: ['comic-vine-mapping', thread?.id],
    queryFn: () => {
      if (!thread?.id) return null;
      
      // The mapping data is already included in the thread data from the queue API
      // This hook provides easy access to the mapping status
      return thread.comicvine_mapping;
    },
    enabled: !!thread?.id,
    staleTime: 5 * 60 * 1000, // 5 minutes
  });
}

/**
 * Helper function to determine mapping status for display
 */
export function getMappingStatus(mapping: ComicVineMappingHealth | null): ComicVineMappingStatus | null {
  if (!mapping) return null;
  return mapping.status;
}

/**
 * Helper function to get mapping status text for display
 */
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

/**
 * Helper function to get mapping status description for display
 */
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

/**
 * Helper function to check if a thread needs mapping attention
 */
export function needsMappingAttention(mapping: ComicVineMappingHealth | null): boolean {
  if (!mapping) return false;
  
  return mapping.status === 'partial' || 
         mapping.status === 'unresolved' || 
         mapping.status === 'needs_review';
}

/**
 * Helper function to check if a thread has confirmed mappings
 */
export function hasConfirmedMappings(mapping: ComicVineMappingHealth | null): boolean {
  if (!mapping) return false;
  
  return mapping.confirmed_issue_count > 0;
}

/**
 * Helper function to get the mapping health summary text
 */
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