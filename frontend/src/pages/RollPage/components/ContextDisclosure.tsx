import { useState } from 'react'
import type { ReaderContextResponse } from '../../../services/api-reader-context'
import { SeriesPanel } from './SeriesPanel'
import { CrossoverAnalytics } from './CrossoverAnalytics'

interface ContextDisclosureProps {
  readerContext: ReaderContextResponse | null
  isLoading: boolean
}

function ReaderContextLoading() {
  return (
    <div className="space-y-2 rounded-2xl p-3" style={{ border: '1px solid rgba(168,85,247,0.1)', backgroundColor: 'var(--theme-bg-panel)' }}>
      <div className="h-3 w-24 animate-pulse rounded bg-white/5" />
      <div className="h-5 w-16 animate-pulse rounded bg-white/5" />
      <div className="h-3 w-20 animate-pulse rounded bg-white/5" />
    </div>
  )
}

export function ContextDisclosure({ readerContext, isLoading }: ContextDisclosureProps) {
  const [isOpen, setIsOpen] = useState(false)

  const hasSeriesContent = readerContext?.series && readerContext.series.identity_source !== 'unavailable'
  const hasCrossoverContent = readerContext?.crossovers && readerContext.crossovers.length > 0

  if (isLoading) {
    return <ReaderContextLoading />
  }

  if (!readerContext || (!hasSeriesContent && !hasCrossoverContent)) {
    return null
  }

  return (
    <div className="space-y-3" data-testid="context-disclosure">
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center justify-between gap-3 rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-3 py-2.5 text-left transition hover:bg-white/5 focus:ring-2 focus:ring-[var(--theme-focus-ring)]"
        aria-expanded={isOpen}
        data-testid="context-disclosure-trigger"
      >
        <span className="text-[10px] font-black uppercase tracking-[0.18em] text-stone-500">
          Series history & crossovers
        </span>
        <svg
          className={`h-4 w-4 shrink-0 text-stone-400 transition-transform ${isOpen ? 'rotate-180' : ''}`}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M6 9l6 6 6-6" />
        </svg>
      </button>

      {isOpen && (
        <div className="space-y-3 animate-in slide-in-from-top-2 duration-150" data-testid="context-disclosure-content">
          {hasSeriesContent && <SeriesPanel series={readerContext.series!} />}
          {hasCrossoverContent && <CrossoverAnalytics crossovers={readerContext.crossovers!} />}
        </div>
      )}
    </div>
  )
}