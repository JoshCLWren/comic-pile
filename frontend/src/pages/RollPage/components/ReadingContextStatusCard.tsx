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
        className="rounded-2xl p-3"
        style={{ border: '1px solid rgba(6,182,212,0.1)', backgroundColor: 'rgba(6, 182, 212, 0.04)' }}
        role="status"
        aria-live="polite"
      >
        <h3
          id="reader-context-loading-heading"
          className="font-black text-stone-300"
          style={readingContextType('bodyCopy')}
        >
          Checking reading context…
        </h3>
        <div className="mt-2 h-3 w-24 animate-pulse rounded bg-white/5" />
      </section>
    )
  }

  if (error) {
    return (
      <section
        aria-labelledby="reader-context-unavailable-heading"
        className="rounded-2xl p-3"
        style={{ border: '1px solid rgba(6,182,212,0.3)', backgroundColor: 'rgba(6, 182, 212, 0.09)' }}
        role="alert"
      >
        <h3
          id="reader-context-unavailable-heading"
          className="font-black text-rose-300"
          style={readingContextType('sectionHeading')}
        >
          Local reading context unavailable
        </h3>
        <p className="mt-1 text-stone-400" style={readingContextType('bodyCopy')}>
          {error}
        </p>
      </section>
    )
  }

  return null
}