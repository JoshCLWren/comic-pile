import { useState } from 'react'

interface CompletedThread {
  id: number
  title: string
  format: string
  notes?: string | null
}

interface CompletedThreadsSectionProps {
  threads: CompletedThread[]
  onReactivate: (thread: CompletedThread | null) => void
}

export default function CompletedThreadsSection({
  threads,
  onReactivate,
}: CompletedThreadsSectionProps) {
  const [isExpanded, setIsExpanded] = useState(false)

  if (threads.length === 0) return null

  return (
    <section className="space-y-4" aria-labelledby="completed-threads-heading">
      <header className="flex items-center justify-between gap-3 px-2">
        <div className="min-w-0">
          <h2
            id="completed-threads-heading"
            className="text-lg md:text-xl font-black uppercase text-stone-300"
          >
            Completed Threads
          </h2>
          <p className="text-[10px] font-bold text-stone-500 uppercase tracking-widest">
            {threads.length} finished {threads.length === 1 ? 'series' : 'series'} hidden from the queue
          </p>
        </div>
        <button
          type="button"
          onClick={() => setIsExpanded((expanded) => !expanded)}
          aria-expanded={isExpanded}
          aria-controls="completed-thread-list"
          className="h-8 md:h-10 px-3 md:px-4 bg-white/5 border border-white/10 rounded-xl text-[10px] font-black uppercase tracking-widest text-stone-300 hover:bg-white/10"
        >
          {isExpanded ? 'Hide Completed' : `Show Completed (${threads.length})`}
        </button>
      </header>

      {isExpanded && (
        <div id="completed-thread-list" className="space-y-4">
          <div className="flex justify-end px-2">
            <button
              type="button"
              onClick={() => onReactivate(null)}
              className="h-8 md:h-10 px-3 md:px-4 bg-white/5 border border-white/10 rounded-xl text-[10px] font-black uppercase tracking-widest text-stone-300 hover:bg-white/10"
            >
              Reactivate
            </button>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {threads.map((thread) => (
              <div key={thread.id} className="glass-card p-4 space-y-2">
                <div className="flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-sm font-black text-stone-300 truncate">{thread.title}</p>
                    <p className="text-[8px] font-black text-stone-500 uppercase tracking-widest">
                      {thread.format}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => onReactivate(thread)}
                    className="px-3 py-1 bg-white/5 border border-white/10 rounded-lg text-[9px] font-black uppercase tracking-widest text-stone-300 hover:bg-white/10"
                  >
                    Reactivate
                  </button>
                </div>
                {thread.notes && <p className="text-xs text-stone-500">{thread.notes}</p>}
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  )
}
