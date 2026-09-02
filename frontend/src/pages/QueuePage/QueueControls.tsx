import { memo, useEffect, useRef, useState } from 'react'
import type { QueueSortBy } from './useQueueFilters'

const SEARCH_DEBOUNCE_MS = 300

interface QueueControlsProps {
  activeCount: number
  shuffleDisabled: boolean
  shufflePending: boolean
  onShuffle: () => void
  onCreateThread: () => void
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
  sortBy,
  onSortChange,
  searchQuery,
  onSearchChange,
}: QueueControlsProps) {
  const [localValue, setLocalValue] = useState(searchQuery)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

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
            Read Queue
          </h1>
          <p className="text-[10px] font-bold text-stone-500 uppercase tracking-widest">
            Your upcoming comics
          </p>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-1.5 md:gap-2 shrink-0">
          <button
            type="button"
            onClick={onShuffle}
            disabled={shuffleDisabled || shufflePending}
            className="h-9 md:h-12 px-3 md:px-5 rounded-lg border border-white/10 bg-white/5 text-[10px] md:text-xs font-black uppercase tracking-widest whitespace-nowrap text-stone-300 hover:bg-white/10 disabled:opacity-50"
          >
            Shuffle
          </button>
          <button
            type="button"
            onClick={onCreateThread}
            className="hidden md:flex h-12 px-5 glass-button text-xs font-black uppercase tracking-widest whitespace-nowrap shadow-xl"
            data-testid="queue-add-thread-desktop"
          >
            Add Thread
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
              {sort === 'position' ? 'Pos' : sort === 'alphabetical' ? 'A-Z' : 'New'}
            </button>
          ))}
        </div>
        <input
          type="text"
          value={localValue}
          onChange={(e) => {
            const next = e.target.value
            setLocalValue(next)
            if (debounceRef.current) clearTimeout(debounceRef.current)
            debounceRef.current = setTimeout(() => onSearchChange(next), SEARCH_DEBOUNCE_MS)
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              clearTimeout(debounceRef.current as ReturnType<typeof setTimeout> | undefined)
              onSearchChange(localValue)
            }
          }}
          onBlur={() => {
            if (localValue !== searchQuery) {
              clearTimeout(debounceRef.current as ReturnType<typeof setTimeout> | undefined)
              onSearchChange(localValue)
            }
          }}
          placeholder="Search..."
          className="h-9 px-3 bg-white/5 border border-white/10 rounded-lg text-xs text-stone-300 placeholder-stone-500 focus:outline-none focus:ring-2 focus:ring-amber-500/30 focus:border-amber-400 transition-colors w-full md:w-auto"
        />
      </div>
      <span className="sr-only" data-testid="queue-active-count">{activeCount}</span>
    </header>
  )
}

export const QueueControls = memo(QueueControlsInner)
