import { useNavigate } from 'react-router-dom'
import type { Thread } from '../../../types'
import type { RatingThread } from '../types'

interface ThreadPoolProps {
  pool: Thread[]
  blockedThreads: Thread[]
  blockingReasonMap: Record<number, string[]>
  isRatingView: boolean
  isRolling: boolean
  rolledResult: number | null
  selectedThreadId: number | null
  staleThread: (Thread & { days: number }) | null
  staleThreadCount: number
  snoozedThreads: Array<{ id: number; title: string; format: string }>
  snoozedExpanded: boolean
  blockedExpanded: boolean
  onThreadClick: (thread: Thread) => void
  onUnsnooze: (threadId: number) => void
  onReadStale: () => void
  onToggleSnoozed: () => void
  onToggleBlocked: () => void
  unsnoozeIsPending: boolean
}

export function ThreadPool({
  pool,
  blockedThreads,
  blockingReasonMap,
  isRatingView,
  isRolling,
  rolledResult,
  selectedThreadId,
  staleThread,
  staleThreadCount,
  snoozedThreads,
  snoozedExpanded,
  blockedExpanded,
  onThreadClick,
  onUnsnooze,
  onReadStale,
  onToggleSnoozed,
  onToggleBlocked,
  unsnoozeIsPending,
}: ThreadPoolProps) {
  const navigate = useNavigate()
  return (
    <div className={`px-4 pb-4 flex flex-col ${!isRatingView ? 'flex-1 min-h-[300px]' : 'border-t border-white/5 pt-8'}`}>
      {!isRolling && rolledResult === null && !isRatingView && pool.length > 0 && (
        <p
          id="tap-instruction"
          className="text-stone-500 font-black uppercase tracking-[0.5em] text-[10px] animate-pulse shrink-0 text-center mb-8"
        >
          Tap Die to Roll
        </p>
      )}

      <div className="flex items-center gap-2 shrink-0 mb-4">
        <div className="w-2 h-2 rounded-full bg-amber-600 shadow-[0_0_15px_var(--accent-red)]"></div>
        <div className="flex-1">
          <p className="text-[10px] font-black uppercase tracking-wider text-stone-300">Roll Pool</p>
        </div>
      </div>

      <div className="space-y-2" data-roll-pool aria-label="Roll pool collection">
        {pool.length === 0 && blockedThreads.length === 0 && snoozedThreads.length === 0 ? (
          <div className="text-center py-10 space-y-4">
            <div className="text-4xl">📚</div>
            <div>
              <p className="text-sm text-stone-300 font-bold uppercase tracking-widest">Your Queue Is Empty</p>
              <p className="text-xs text-stone-500 mt-1">Add comics to start rolling.</p>
            </div>
            <div className="flex flex-col sm:flex-row gap-3 w-full max-w-md mx-auto">
              <button
                onClick={() => navigate('/queue', { state: { openCreate: true } })}
                className="w-full h-11 bg-amber-500/10 hover:bg-amber-500/20 border border-amber-500/20 rounded-xl text-xs font-black uppercase tracking-widest text-amber-500"
              >
                Add Thread
              </button>
              <button
                onClick={() => navigate('/queue')}
                className="w-full h-11 sm:h-10 bg-amber-500/20 hover:bg-amber-500/30 border border-amber-500/40 rounded-xl text-xs font-black uppercase tracking-widest text-amber-500 mt-2 sm:mt-0"
              >
                Go to Queue
              </button>
            </div>
          </div>
        ) : pool.length === 0 && blockedThreads.length > 0 ? (
          <div className="text-center py-10 space-y-4">
            <div className="text-4xl">🔒</div>
            <div>
              <p className="text-sm text-stone-300 font-bold uppercase tracking-widest">All Threads Blocked</p>
              <p className="text-xs text-stone-500 mt-1">Resolve dependencies to roll.</p>
            </div>
          </div>
        ) : pool.length === 0 && snoozedThreads.length > 0 && blockedThreads.length === 0 ? (
          <div className="text-center py-10 space-y-4">
            <div className="text-4xl">⏸️</div>
            <div>
              <p className="text-sm text-stone-300 font-bold uppercase tracking-widest">All Threads Snoozed</p>
              <p className="text-xs text-stone-500 mt-1">Wake threads to start rolling.</p>
            </div>
            <button
              onClick={() => navigate('/queue')}
              className="mt-4 px-6 py-3 bg-amber-500/10 hover:bg-amber-500/20 border border-amber-500/20 rounded-xl text-xs font-black uppercase tracking-widest text-amber-500 transition-colors"
            >
              Go to Queue
            </button>
          </div>
        ) : (
          pool.map((thread, index) => {
            const isSelected = selectedThreadId && Number(selectedThreadId) === thread.id
            return (
              <div
                key={thread.id}
                onClick={() => onThreadClick(thread)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    onThreadClick(thread)
                  }
                }}
                role="button"
                tabIndex={0}
                className={`flex items-center gap-3 px-4 py-3 bg-white/5 border border-white/5 rounded-xl group transition-all cursor-pointer hover:bg-white/10 ${isSelected ? 'pool-thread-selected border-amber-500/30' : ''
                  }`}
              >
                <span className="text-lg font-black text-stone-500/50 group-hover:text-stone-400/50 transition-colors w-6 text-center">
                  {index + 1}
                </span>
                <div className="flex-1 min-w-0">
                  <p className="font-bold text-stone-300 truncate text-sm">{thread.title}</p>
                  <p className="text-[10px] font-black text-stone-500 uppercase tracking-widest mt-0.5">{thread.format}</p>
                </div>
              </div>
            )
          })
        )}
      </div>

      {blockedThreads.length > 0 && !isRatingView && (
        <div className="mt-4">
          <button
            type="button"
            onClick={onToggleBlocked}
            className="w-full px-4 py-2 bg-stone-500/5 border border-stone-500/10 rounded-xl flex items-center gap-2 hover:bg-stone-500/10 transition-colors"
          >
            <span
              className={`text-stone-400 text-xs transition-transform ${blockedExpanded ? 'rotate-90' : ''}`}
            >
              ▶
            </span>
            <span className="text-[10px] font-black text-stone-400 uppercase tracking-widest">
              {blockedThreads.length} thread{blockedThreads.length !== 1 ? 's' : ''} hidden (blocked by dependencies)
            </span>
          </button>
          {blockedExpanded && (
            <div className="mt-2 space-y-1">
              {blockedThreads.map((thread) => (
                <div
                  key={thread.id}
                  className="flex items-center gap-2 px-4 py-2 bg-white/5 border border-white/5 rounded-lg"
                >
                  <span className="text-sm">🔒</span>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-stone-400 truncate">{thread.title}</p>
                    {blockingReasonMap[thread.id]?.length > 0 && (
                      <p className="text-[10px] text-stone-500 truncate">{blockingReasonMap[thread.id][0]}</p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {staleThread && !isRatingView && (
        <div
          onClick={onReadStale}
          className="mt-8 animate-[fade-in_0.5s_ease-out] cursor-pointer hover:bg-amber-500/5 transition-colors rounded-xl"
          role="button"
          tabIndex={0}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault()
              onReadStale()
            }
          }}
        >
          <div className="px-4 py-3 bg-amber-500/5 border border-amber-500/10 rounded-xl flex items-center gap-3">
            <div className="w-8 h-8 bg-amber-500/10 rounded-lg flex items-center justify-center shrink-0">
              <span className="text-sm">⏳</span>
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-[10px] font-bold text-amber-200/70 uppercase tracking-wider leading-relaxed">
                {staleThreadCount} stale thread{staleThreadCount !== 1 ? 's' : ''}: <span className="text-amber-400 font-black">{staleThread.title}</span> neglected for{' '}
                <span className="text-amber-400 font-black">{staleThread.days}</span> days
              </p>
              <p className="text-[9px] text-amber-300/70 text-center mt-1">
                Tap to read now
              </p>
            </div>
          </div>
        </div>
      )}

      {snoozedThreads && snoozedThreads.length > 0 && !isRatingView && (
        <div className="mt-8">
          <button
            type="button"
            onClick={onToggleSnoozed}
            className="w-full px-4 py-2 bg-stone-500/5 border border-stone-500/10 rounded-xl flex items-center gap-2 hover:bg-stone-500/10 transition-colors"
          >
            <span
              className={`text-stone-400 text-xs transition-transform ${snoozedExpanded ? 'rotate-90' : ''}`}
            >
              ▶
            </span>
            <span className="text-[10px] font-black text-stone-400 uppercase tracking-widest">
              Snoozed ({snoozedThreads.length})
            </span>
          </button>
          {snoozedExpanded && (
            <div className="mt-2 space-y-1">
              {snoozedThreads.map((thread) => (
                <div
                  key={thread.id}
                  className="flex items-center gap-2 px-4 py-2 bg-white/5 border border-white/5 rounded-lg"
                >
                  <p className="flex-1 text-sm text-stone-400 truncate">{thread.title}</p>
                  <button
                    type="button"
                    onClick={() => onUnsnooze(thread.id)}
                    disabled={unsnoozeIsPending}
                    className="px-2 py-1 text-xs text-rose-400 hover:text-rose-300 hover:bg-rose-500/10 rounded-lg transition-colors disabled:opacity-50"
                    title="Unsnooze this comic"
                    aria-label="Unsnooze this comic"
                  >
                    ✕
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
