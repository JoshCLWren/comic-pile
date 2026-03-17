import { useMemo } from 'react'
import type { Thread, FlowchartDependency } from '../types'
import { getTopologicalPath } from '../utils/topologicalSort'

interface Props {
  threads: Thread[]
  dependencies: FlowchartDependency[]
  blockedIds: Set<number>
}

/**
 * Mobile-friendly vertical timeline view for thread dependencies.
 * Shows reading order with progress indicators: ✅ done, 🔵 next to read, ⬜ upcoming.
 */
export default function DependencyTimeline({ threads, dependencies, blockedIds }: Props) {
  const sortedThreads = useMemo(() => getTopologicalPath(threads, dependencies), [threads, dependencies])

  // Determine reading status for each thread
  const threadStatuses = useMemo(() => {
    let foundNextToRead = false
    return sortedThreads.map((thread) => {
      const isBlocked = blockedIds.has(thread.id)
      const isDone = thread.issues_remaining === 0

      if (isDone) {
        return 'done' as const
      }

      if (!isBlocked && !foundNextToRead) {
        foundNextToRead = true
        return 'next' as const
      }

      return 'upcoming' as const
    })
  }, [sortedThreads, blockedIds])

  if (sortedThreads.length === 0) {
    return <div className="p-4 text-center text-stone-500 text-sm">No dependencies to show.</div>
  }

  return (
    <div
      className="flex flex-col p-2 max-h-[60vh] overflow-y-auto w-full max-w-lg mx-auto scrollbar-thin"
      data-testid="dependency-timeline"
    >
      {sortedThreads.map((thread, index) => {
        const status = threadStatuses[index]
        const isBlocked = blockedIds.has(thread.id)

        const dotColor = {
          done: 'bg-green-500 shadow-[0_0_10px_rgba(34,197,94,0.5)]',
          next: 'bg-blue-500 shadow-[0_0_10px_rgba(59,130,246,0.5)] ring-2 ring-blue-400/50 ring-offset-1 ring-offset-transparent',
          upcoming: isBlocked
            ? 'bg-red-500/80 shadow-[0_0_10px_rgba(239,68,68,0.5)]'
            : 'bg-stone-600',
        }[status]

        const statusIcon = {
          done: '✅',
          next: '🔵',
          upcoming: isBlocked ? '🔒' : '⬜',
        }[status]

        const progressText = thread.total_issues !== null && thread.total_issues > 0
          ? `${thread.total_issues - (thread.issues_remaining ?? 0)}/${thread.total_issues} issues`
          : thread.issues_remaining !== null
            ? `${thread.issues_remaining} remaining`
            : null

        return (
          <div key={thread.id} className="relative flex items-stretch gap-3 group">
            <div className="flex flex-col items-center">
              <div className={`w-3 h-3 rounded-full mt-4 z-10 transition-colors ${dotColor}`} />
              {index < sortedThreads.length - 1 && (
                <div className="w-0.5 bg-gradient-to-b from-white/20 to-white/5 flex-1 my-1 rounded-full" />
              )}
            </div>

            <div className={`flex-1 glass-card p-3 mb-3 flex flex-col transition-all hover:bg-white/10 ${
              status === 'next' ? 'border-blue-500/40 bg-blue-500/5' :
              isBlocked ? 'border-red-500/30' : 'border-white/10'
            }`}>
               <div className="flex justify-between items-start gap-2">
                 <div className="flex-1 min-w-0">
                   <h4 className="text-sm font-bold text-stone-200 leading-tight truncate">{thread.title}</h4>
                   <span className="text-[10px] text-stone-500 uppercase tracking-widest font-bold mt-0.5">{thread.format}</span>
                 </div>
                 <span className="text-sm shrink-0" title={status === 'done' ? 'Completed' : status === 'next' ? 'Read next' : isBlocked ? 'Blocked' : 'Upcoming'}>
                   {statusIcon}
                 </span>
               </div>
               {(progressText || status === 'next') && (
                 <div className="flex items-center gap-2 mt-1.5">
                   {progressText && (
                     <span className="text-xs text-amber-500/80 font-medium flex items-center gap-1.5">
                       <span className="w-1.5 h-1.5 rounded-full bg-amber-500/50" />
                       {progressText}
                     </span>
                   )}
                   {status === 'next' && (
                     <span className="text-[10px] font-black uppercase tracking-widest text-blue-400 bg-blue-500/10 px-2 py-0.5 rounded-full">
                       Read next
                     </span>
                   )}
                 </div>
               )}
            </div>
          </div>
        )
      })}
    </div>
  )
}
