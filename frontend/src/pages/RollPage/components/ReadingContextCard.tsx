import type { ReactNode } from 'react'
import { readingContextType } from '../readingContextTypography'
import { ReadingContextStatusCard } from './ReadingContextStatusCard'

interface ReadingContextCardProps {
  isLoading: boolean
  error: string | null
  isOpen: boolean
  onToggle: () => void
  children: ReactNode
}

export function ReadingContextCard({ isLoading, error, isOpen, onToggle, children }: ReadingContextCardProps) {
  return (
    <div className="space-y-3" data-testid="reading-context-card">
      <button
        type="button"
        onClick={onToggle}
        className="w-full flex items-center justify-between gap-3 rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-3 py-2.5 text-left transition hover:bg-white/5 focus:ring-2 focus:ring-[var(--theme-focus-ring)]"
        aria-expanded={isOpen}
        data-testid="reading-context-button"
      >
        <div className="flex items-center gap-3">
          <svg
            className="h-4 w-4 shrink-0 text-stone-400"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
            <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
          </svg>
          <div className="flex flex-col">
            <span className="text-[10px] font-black uppercase tracking-[0.18em] text-stone-500">
              Reading Context (Optional)
            </span>
            <span className="text-[11px] text-stone-400" style={readingContextType('bodyCopy')}>
              See how this issue fits into your reading plans and continuity.
            </span>
          </div>
        </div>
        <span className="text-[10px] font-black uppercase tracking-wider text-stone-500 hover:text-stone-300 transition-colors">
          {isOpen ? 'Hide Context' : 'Show Context'}
        </span>
      </button>

      {isOpen && (
        <div
          className="animate-in slide-in-from-top-2 duration-150"
          data-testid="reading-context-content"
        >
          {isLoading ? (
            <ReadingContextStatusCard isLoading error={error} />
          ) : error ? (
            <ReadingContextStatusCard isLoading={false} error={error} />
          ) : (
            children
          )}
        </div>
      )}
    </div>
  )
}
