import { useState } from 'react'
import type { ThreadListItem } from '../../types'

interface ExcludedThreadsSectionProps {
  threads: ThreadListItem[]
  isRestoring: boolean
  error: string | null
  onRestore: (threadId: number) => void
}

/**
 * Discoverable library view for series removed from the queue (#3807).
 *
 * "Remove from Queue" is non-destructive: the thread keeps its issues, read
 * state, ratings, mappings, and reading-plan memberships. That makes an
 * excluded series recoverable rather than gone, so this section is the only
 * surface a reader can restore from. Its copy states the remaining unread
 * count so the shelf reads as preserved history, not as a deleted list.
 *
 * Mirrors `CompletedThreadsSection`: collapsed by default, and rendered
 * nothing at all when there is nothing excluded.
 */
export default function ExcludedThreadsSection({
  threads,
  isRestoring,
  error,
  onRestore,
}: ExcludedThreadsSectionProps) {
  const [isExpanded, setIsExpanded] = useState(false)

  if (threads.length === 0) return null

  return (
    <section
      className="space-y-4"
      aria-labelledby="removed-from-queue-heading"
      data-testid="excluded-threads-section"
    >
      <header className="flex items-center justify-between gap-3 px-2">
        <div className="min-w-0">
          <h2
            id="removed-from-queue-heading"
            className="text-lg md:text-xl font-black uppercase text-stone-300"
          >
            Removed from Queue
          </h2>
          <p className="text-[10px] font-bold text-stone-500 uppercase tracking-widest">
            {threads.length} series kept out of the queue with history intact
          </p>
        </div>
        <button
          type="button"
          onClick={() => setIsExpanded((expanded) => !expanded)}
          aria-expanded={isExpanded}
          aria-controls="excluded-thread-list"
          className="h-8 md:h-10 px-3 md:px-4 bg-white/5 border border-white/10 rounded-xl text-[10px] font-black uppercase tracking-widest text-stone-300 hover:bg-white/10"
        >
          {isExpanded ? 'Hide Removed' : `Show Removed (${threads.length})`}
        </button>
      </header>

      <div id="excluded-thread-list" className="space-y-4" hidden={!isExpanded}>
        {error && (
          <p
            role="alert"
            className="px-2 text-sm text-red-400"
            data-testid="excluded-threads-error"
          >
            {error}
          </p>
        )}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {threads.map((thread) => (
            <div key={thread.id} className="surface-panel p-4 space-y-2">
              <div className="flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-sm font-black text-stone-300 truncate">{thread.title}</p>
                  <p className="text-[8px] font-black text-stone-500 uppercase tracking-widest">
                    {thread.format}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => onRestore(thread.id)}
                  disabled={isRestoring}
                  aria-label={`Restore ${thread.title} to queue`}
                  className="px-3 py-1 bg-white/5 border border-white/10 rounded-lg text-[9px] font-black uppercase tracking-widest text-stone-300 hover:bg-white/10 disabled:opacity-50"
                >
                  Restore to Queue
                </button>
              </div>
              <p className="text-xs text-stone-500">
                {thread.issues_remaining} unread preserved
              </p>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}