import Tooltip from './Tooltip'
import { getMappingHealthDescription, getMappingHealthLabel } from '../utils/comicVineMapping'
import type { ComicVineMappingHealth, ComicVineMappingStatus } from '../types/comic-vine'

interface MappingStatusIndicatorProps {
  mapping: ComicVineMappingHealth
  className?: string
}

const STATUS_CLASSES: Record<ComicVineMappingStatus, string> = {
  not_applicable: 'text-[var(--theme-text-muted)] border-[var(--theme-border)] bg-[var(--theme-bg-panel)]',
  fully_mapped: 'text-[var(--theme-text-muted)] border-[var(--theme-border)] bg-[var(--theme-bg-panel)]',
  partial: 'text-[var(--theme-warning)] border-[var(--theme-warning)]/30 bg-[var(--theme-warning)]/10',
  unresolved: 'text-[var(--theme-warning)] border-[var(--theme-warning)]/30 bg-[var(--theme-warning)]/10',
  needs_review: 'text-[var(--theme-danger)] border-[var(--theme-danger)]/30 bg-[var(--theme-danger)]/10',
}

const STATUS_ICONS: Record<ComicVineMappingStatus, string> = {
  not_applicable: '○',
  fully_mapped: '✓',
  partial: '◐',
  unresolved: '○',
  needs_review: '⚠',
}

/**
 * The single compact mapping-health chip a queue series shows.
 *
 * Callers render it only for series that still need repair, so a fully mapped
 * series keeps no mapping chrome. The state and its counts are rendered as
 * text; color and the decorative glyph only reinforce them.
 */
export function MappingStatusIndicator({ mapping, className = '' }: MappingStatusIndicatorProps) {
  return (
    <Tooltip content={getMappingHealthDescription(mapping)}>
      <span
        data-testid="queue-mapping-health"
        className={`inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-full border px-2 py-0.5 text-xs font-bold ${STATUS_CLASSES[mapping.status]} ${className}`}
      >
        <span aria-hidden="true">{STATUS_ICONS[mapping.status]}</span>
        {getMappingHealthLabel(mapping)}
      </span>
    </Tooltip>
  )
}