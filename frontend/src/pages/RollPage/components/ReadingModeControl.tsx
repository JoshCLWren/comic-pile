import { formatReadingMode, type ReadingModeDisplay } from '../../../types/readingMode'

interface ReadingModeControlProps {
  mode: ReadingModeDisplay | null | undefined
}

/**
 * Compact `Light · Momentum` indicator for the Roll header.
 * Purely presentational: it reads the canonical scoped reading-mode resource
 * and never exposes raw confidence scores. Renders nothing while unavailable.
 */
export function ReadingModeControl({ mode }: ReadingModeControlProps) {
  const label = formatReadingMode(mode)
  if (!mode || !label) return null

  return (
    <span
      data-testid="reading-mode-control"
      title={`Reading mode: ${label}`}
      className="inline-flex max-w-[11rem] min-h-11 items-center gap-1 rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-2 md:px-3 py-1.5 text-[10px] font-black uppercase tracking-widest text-[var(--theme-text-muted)]"
    >
      <span className="truncate">{label}</span>
    </span>
  )
}
