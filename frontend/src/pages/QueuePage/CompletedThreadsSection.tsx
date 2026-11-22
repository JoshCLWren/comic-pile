import { useState } from 'react'
import LoadingSpinner from '../../components/LoadingSpinner'

interface CompletedThread {
  id: number
  title: string
  format: string
  notes?: string | null
}

interface CompletedThreadsSectionProps<T extends CompletedThread> {
  threads: T[]
  onReactivate: (thread: T | null) => void
  hasNextPage?: boolean
  isLoadingMore?: boolean
  isError?: boolean
  isLoading?: boolean
  onLoadMore?: () => Promise<void> | void
  onRetry?: () => Promise<void> | void
}

/** Finished series are a separate, cursor-paginated collection from active Queue rows. */
export default function CompletedThreadsSection<T extends CompletedThread>({
  threads,
  onReactivate,
  hasNextPage = false,
  isLoadingMore = false,
  isError = false,
  isLoading = false,
  onLoadMore,
  onRetry,
}: CompletedThreadsSectionProps<T>) {
  const [isExpanded, setIsExpanded] = useState(false)

  if (threads.length === 0 && !isError) {
    // An empty settled shelf means "no finished series"; an empty in-flight
    // shelf means "the first page has not landed yet" and must not render as
    // nothing (the original #5171 disappearance, now guarded at the source).
    if (isLoading) {
      return (
        <section className="space-y-4" aria-labelledby="finished-series-heading">
          <h2
            id="finished-series-heading"
            className="text-lg md:text-xl font-black uppercase text-stone-300"
          >
            Finished Series
          </h2>
          <div
            className="flex items-center justify-center px-2 py-8"
            data-testid="completed-threads-loading"
          >
            <LoadingSpinner message="Loading finished series..." />
          </div>
        </section>
      )
    }
    return null
  }

  const handleReactivate = (thread: T | null) => {
    setIsExpanded(false)
    onReactivate(thread)
  }
  // The Rust collection returns a continuation cursor, not a total count.
  const loadedCount = `${threads.length}${hasNextPage ? '+' : ''}`

  return (
    <section className="space-y-4" aria-labelledby="finished-series-heading">
      <header className="flex items-center justify-between gap-3 px-2">
        <div className="min-w-0">
          <h2
            id="finished-series-heading"
            className="text-lg md:text-xl font-black uppercase text-stone-300"
          >
            Finished Series
          </h2>
          <p className="text-[10px] font-bold text-stone-500 uppercase tracking-widest">
            {threads.length} finished series loaded{hasNextPage ? ', more available' : ''}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {threads.length > 0 && (
            <>
              <button
                type="button"
                onClick={() => handleReactivate(null)}
                className="h-8 md:h-10 px-3 md:px-4 bg-white/5 border border-white/10 rounded-xl text-[10px] font-black uppercase tracking-widest text-stone-300 hover:bg-white/10"
              >
                Add back to queue
              </button>
              <button
                type="button"
                onClick={() => setIsExpanded((expanded) => !expanded)}
                aria-expanded={isExpanded}
                aria-controls="completed-thread-list"
                className="h-8 md:h-10 px-3 md:px-4 bg-white/5 border border-white/10 rounded-xl text-[10px] font-black uppercase tracking-widest text-stone-300 hover:bg-white/10"
              >
                {isExpanded ? 'Hide Finished' : `Show Finished (${loadedCount})`}
              </button>
            </>
          )}
        </div>
      </header>

      {isError && (
        <div role="alert" className="text-sm text-red-400 px-2">
          Couldn&apos;t load finished series.
          {onRetry && (
            <button
              type="button"
              className="ml-2 underline"
              onClick={() => { void onRetry() }}
            >
              Try again
            </button>
          )}
        </div>
      )}

      <div id="completed-thread-list" className="space-y-4" hidden={!isExpanded}>
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
                  onClick={() => handleReactivate(thread)}
                  aria-label={`Add ${thread.title} back to queue`}
                  className="px-3 py-1 bg-white/5 border border-white/10 rounded-lg text-[9px] font-black uppercase tracking-widest text-stone-300 hover:bg-white/10"
                >
                  Add back to queue
                </button>
              </div>
              {thread.notes && <p className="text-xs text-stone-500">{thread.notes}</p>}
            </div>
          ))}
        </div>
        {hasNextPage && onLoadMore && (
          <button
            type="button"
            disabled={isLoadingMore}
            onClick={() => { void onLoadMore() }}
            className="mx-auto block rounded-md bg-white/5 border border-white/10 px-4 py-2 text-sm font-semibold text-stone-300 hover:bg-white/10 disabled:opacity-50"
          >
            {isLoadingMore ? 'Loading more finished series...' : 'Load more finished series'}
          </button>
        )}
      </div>
    </section>
  )
}
