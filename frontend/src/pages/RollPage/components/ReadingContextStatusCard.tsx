import { readingContextType } from '../readingContextTypography'

interface ReadingContextStatusCardProps {
  isLoading: boolean
  error: string | null
}

/**
 * Bounded replacement for the Reading Context pillar while the reader context
 * is still loading or failed. The card never reserves the full pillar column:
 * it is a small strip so a successful-empty state stays visually absent while
 * transient states remain distinguishable from it.
 */
export function ReadingContextStatusCard({ isLoading, error }: ReadingContextStatusCardProps) {
  if (isLoading) {
    return (
      <section
        aria-labelledby="reader-context-loading-heading"
        className="rounded-2xl border border-[var(--theme-continuity-accent)]/10 bg-[var(--theme-continuity-accent)]/5 p-3"
        role="status"
        aria-live="polite"
      >
        <h3
          id="reader-context-loading-heading"
          className="font-black text-[var(--theme-text-primary)]"
          style={readingContextType('bodyCopy')}
        >
          Checking reading context…
        </h3>
        <div className="mt-2 h-3 w-24 animate-pulse rounded bg-[var(--theme-bg-hover)]" />
      </section>
    )
  }

  if (error) {
    return (
      <section
        aria-labelledby="reader-context-unavailable-heading"
        className="rounded-2xl border border-[var(--theme-error)]/30 bg-[var(--theme-error)]/10 p-3"
        role="alert"
      >
        <h3
          id="reader-context-unavailable-heading"
          className="font-black text-[var(--theme-error)]"
          style={readingContextType('sectionHeading')}
        >
          Local reading context unavailable
        </h3>
        <p className="mt-1 text-[var(--theme-text-muted)]" style={readingContextType('bodyCopy')}>
          {error}
        </p>
      </section>
    )
  }

  return null
}