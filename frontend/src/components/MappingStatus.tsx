import React from 'react';
import { 
  getMappingStatusText, 
  getMappingStatusDescription, 
  getMappingSummary,
} from '../utils/comicVineMapping';
import type { ComicVineMappingHealth, ComicVineMappingStatus } from '../types/comic-vine';

interface MappingStatusBadgeProps {
  mapping: ComicVineMappingHealth | null;
  showDetails?: boolean;
  className?: string;
}

interface MappingStatusIndicatorProps {
  status: ComicVineMappingStatus | null;
  count?: number;
  className?: string;
}

const statusColors: Record<ComicVineMappingStatus, string> = {
  not_applicable: 'text-[var(--theme-text-muted)] bg-[var(--theme-bg-panel)] border border-[var(--theme-border)]',
  fully_mapped: 'text-[var(--theme-text-muted)] bg-[var(--theme-bg-panel)] border border-[var(--theme-border)]',
  partial: 'text-[var(--theme-warning)] bg-[color-mix(in_srgb,var(--theme-warning)_8%,transparent)] border border-[color-mix(in_srgb,var(--theme-warning)_30%,transparent)]',
  unresolved: 'text-[var(--theme-warning)] bg-[color-mix(in_srgb,var(--theme-warning)_8%,transparent)] border border-[color-mix(in_srgb,var(--theme-warning)_30%,transparent)]',
  needs_review: 'text-[var(--theme-danger)] bg-[color-mix(in_srgb,var(--theme-danger)_8%,transparent)] border border-[color-mix(in_srgb,var(--theme-danger)_30%,transparent)]',
};

const statusIcons: Record<ComicVineMappingStatus, string> = {
  not_applicable: '○',
  fully_mapped: '✓',
  partial: '◐',
  unresolved: '○',
  needs_review: '⚠',
};

export function MappingStatusBadge({ 
  mapping, 
  showDetails = false, 
  className = '' 
}: MappingStatusBadgeProps) {
  if (!mapping) {
    return null;
  }

  const statusText = getMappingStatusText(mapping.status);
  const statusDescription = getMappingStatusDescription(mapping);
  const summary = getMappingSummary(mapping);

  return (
    <div className={`inline-flex items-center gap-1 rounded-full px-2 py-1 text-xs font-medium ${statusColors[mapping.status]} ${className}`}>
      <span className="text-[10px]">{statusIcons[mapping.status]}</span>
      <span className="font-bold">{statusText}</span>
      {showDetails && (
        <span className="font-normal opacity-75">({summary})</span>
      )}
      <span className="sr-only">{statusDescription}</span>
    </div>
  );
}

export function MappingStatusIndicator({ 
  status, 
  count, 
  className = '' 
}: MappingStatusIndicatorProps) {
  if (!status) {
    return null;
  }

  return (
    <div className={`inline-flex items-center gap-1 rounded-full px-2 py-1 text-xs font-medium ${statusColors[status]} ${className}`}>
      <span className="text-[10px]">{statusIcons[status]}</span>
      <span className="font-bold">{getMappingStatusText(status)}</span>
      {count !== undefined && count > 0 && (
        <span className="font-normal opacity-75">({count})</span>
      )}
    </div>
  );
}

interface MappingHealthSummaryProps {
  mapping: ComicVineMappingHealth | null;
  className?: string;
}

export function MappingHealthSummary({ mapping, className = '' }: MappingHealthSummaryProps) {
  if (!mapping) {
    return null;
  }

  const needsMapping = mapping.needs_mapping_count > 0;
  const needsReview = mapping.needs_review_count > 0;

  return (
    <div className={`flex flex-wrap items-center gap-2 text-xs ${className}`}>
      <MappingStatusIndicator 
        status={mapping.status} 
        count={mapping.tracked_issue_count}
      />
      
      {needsMapping && (
        <span className="text-[var(--theme-warning)]">
          {mapping.needs_mapping_count} need mapping
        </span>
      )}
      
      {needsReview && (
        <span className="text-[var(--theme-danger)]">
          {mapping.needs_review_count} need review
        </span>
      )}
      
      {mapping.confirmed_issue_count > 0 && (
        <span className="text-[var(--theme-comic-accent)]">
          {mapping.confirmed_issue_count} mapped
        </span>
      )}
    </div>
  );
}