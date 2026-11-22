import { memo, useEffect, useRef, useState } from 'react'
import type { QueueSortBy } from './useQueueFilters'

const SEARCH_DEBOUNCE_MS = 400

interface QueueControlsProps {
  activeCount: number
  shuffleDisabled: boolean
  shufflePending: boolean
  onShuffle: () => void
  onCreateThread: () => void
  onAddFromComicVine: () => void
  onBulkMapSeries: () => void
  /**
   * True when no unmapped series are available for bulk mapping. The bulk
   * action stays visible but disabled so phones and desktops agree.
   */
  bulkMapDisabled?: boolean
  sortBy: QueueSortBy
  onSortChange: (next: QueueSortBy) => void
  searchQuery: string
  onSearchChange: (next: string) => void
}

/**
 * Header, sort selector, search input, shuffle, and add-thread controls for
 * the Queue page. Receives only presentational props and renders the
 * well-known selectors (`Shuffle`, sort buttons, search box, etc.) without
 * owning any of the underlying query or mutation state.
 *
 * Search input is locally owned and debounced so that every keystroke does
 * not trigger a parent re-render or a new queue query. The parent only
 * receives the committed value after {@link SEARCH_DEBOUNCE_MS}.
 */
function QueueControlsInner({
  activeCount,
  shuffleDisabled,
  shufflePending,
  onShuffle,
  onCreateThread,
  onAddFromComicVine,
  onBulkMapSeries,
  bulkMapDisabled = false,
  sortBy,
  onSortChange,
  searchQuery,
  onSearchChange,
}: QueueControlsProps) {
  const [localValue, setLocalValue] = useState(searchQuery)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const searchInputRef = useRef<HTMLInputElement>(null)

  const clearSearch = () => {
    if (debounceRef.current) {
      clearTimeout(debounceRef.current)
      debounceRef.current = null
    }
    setLocalValue('')
    onSearchChange('')
    searchInputRef.current?.focus()
  }

  useEffect(() => {
    setLocalValue(searchQuery)
  }, [searchQuery])

  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [])
  return (
    <header className="space-y-3 md:space-y-4 px-2">
      <div className="flex flex-wrap justify-between items-start gap-2 md:gap-4">
        <div className="min-w-0">
          <h1 className="text-2xl md:text-4xl font-black tracking-tighter text-glow mb-1 uppercase">
            Queue
          </h1>
          <p className="text-base font-semibold text-stone-500">
            Your upcoming comics
          </p>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-1.5 md:gap-2 shrink-0">
          <button
            type="button"
            onClick={onShuffle}
            disabled={shuffleDisabled || shufflePending}
            className="h-9 md:h-12 px-3 md:px-5 rounded-lg border border-[var(--theme-danger)]/40 bg-[var(--theme-danger)]/10 text-[10px] md:text-xs font-black uppercase tracking-widest whitespace-nowrap text-[var(--theme-danger)] hover:bg-[var(--theme-danger)]/20 disabled:opacity-50 transition-colors"
          >
            Shuffle
          </button>
          <button
            type="button"
            onClick={onAddFromComicVine}
            className="hidden md:flex h-12 px-5 rounded-xl bg-[var(--theme-bg-panel)] border border-[var(--theme-border)] text-stone-200 font-semibold whitespace-nowrap hover:bg-[var(--theme-bg-hover)] items-center gap-2"
            data-testid="queue-add-comicvine-desktop"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            Add from ComicVine
          </button>
          <button
            type="button"
            onClick={onBulkMapSeries}
            disabled={bulkMapDisabled}
            className="hidden md:flex h-12 px-5 rounded-xl bg-[var(--theme-bg-panel)] border border-[var(--theme-border)] text-[var(--theme-text-primary)] font-semibold whitespace-nowrap hover:bg-[var(--theme-bg-hover)] items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
            data-testid="queue-bulk-map-desktop"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            Map Series
          </button>
          <button
            type="button"
            onClick={onBulkMapSeries}
            disabled={bulkMapDisabled}
            className="md:hidden h-9 px-3 rounded-lg bg-[var(--theme-bg-panel)] border border-[var(--theme-border)] text-sm font-bold text-[var(--theme-text-primary)] whitespace-nowrap hover:bg-[var(--theme-bg-hover)] disabled:opacity-50 disabled:cursor-not-allowed"
            data-testid="queue-bulk-map-mobile"
          >
            Map Series
          </button>
          <button
            type="button"
            onClick={onCreateThread}
            className="hidden md:flex h-12 px-5 rounded-xl bg-[var(--theme-primary-action)] font-black text-stone-950 whitespace-nowrap hover:bg-[var(--theme-primary-action-hover)] items-center"
            data-testid="queue-add-thread-desktop"
          >
            Add Series
          </button>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-1">
          {(['position', 'alphabetical', 'created'] as const).map((sort) => (
            <button
              key={sort}
              type="button"
              onClick={() => onSortChange(sort)}
              className={`px-2.5 md:px-3 py-1.5 rounded-lg text-[10px] font-black uppercase tracking-widest transition-colors ${
                sortBy === sort
                  ? 'bg-amber-600/20 text-amber-400 border border-amber-500/30'
                  : 'bg-white/5 text-stone-400 border border-white/10 hover:bg-white/10'
              }`}
            >
              {sort === 'position' ? 'Position' : sort === 'alphabetical' ? 'Title' : 'Recently added'}
            </button>
          ))}
        </div>
        <div className="relative w-full md:w-auto">
          <input
            ref={searchInputRef}
            type="text"
            value={localValue}
            aria-label="Search series"
            onChange={(e) => {
              const next = e.target.value
              setLocalValue(next)
              if (debounceRef.current) clearTimeout(debounceRef.current)
              debounceRef.current = setTimeout(() => onSearchChange(next), SEARCH_DEBOUNCE_MS)
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                // SAFETY: clearTimeout tolerates an undefined/number timer handle; the cast unifies the ref's null initial value.
                clearTimeout(debounceRef.current as ReturnType<typeof setTimeout> | undefined)
                onSearchChange(localValue)
              } else if (e.key === 'Escape' && (localValue !== '' || searchQuery !== '')) {
                // #3539: Escape belongs to the search field while focus is in
                // it. Clear immediately (no debounce) and keep focus here so
                // the reader can type a new query without reaching for
                // the pointer.
                e.preventDefault()
                clearSearch()
              }
            }}
            onBlur={() => {
              if (localValue !== searchQuery) {
                // SAFETY: clearTimeout tolerates an undefined/number timer handle; the cast unifies the ref's null initial value.
                clearTimeout(debounceRef.current as ReturnType<typeof setTimeout> | undefined)
                onSearchChange(localValue)
              }
            }}
            placeholder="Search..."
            className={`h-9 pl-3 rounded-lg text-xs form-control w-full md:w-64 ${localValue ? 'pr-9' : 'pr-3'}`}
          />
          {localValue && (
            <button
              type="button"
              aria-label="Clear search"
              title="Clear search"
              onMouseDown={(e) => e.preventDefault()}
              onClick={clearSearch}
              className="absolute inset-y-0 right-0 flex w-9 items-center justify-center rounded-r-lg text-[var(--theme-text-muted)] hover:text-[var(--theme-text-primary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
            >
              <span aria-hidden="true" className="text-base leading-none">×</span>
            </button>
          )}
        </div>
      </div>
      <span className="sr-only" data-testid="queue-active-count">{activeCount}</span>
    </header>
  )
}

export const QueueControls = memo(QueueControlsInner)
