import { useSessions } from '../hooks/useSession'
import { Link } from 'react-router-dom'

export default function HistoryPage() {
  const { data: sessions, isPending, isLoadingMore, hasMore, loadMore, error } = useSessions()

  if (isPending) {
    return <div className="flex items-center justify-center h-screen">Loading...</div>
  }

  if (error && !isLoadingMore && (!sessions || sessions.length === 0)) {
    return <div className="error-message">Failed to load sessions</div>
  }

  if (!sessions || sessions.length === 0) {
    return (
      <div className="space-y-6 md:space-y-8 pb-20">
        <header className="flex flex-wrap items-end justify-between gap-3 px-2">
          <div>
            <h1 className="text-2xl md:text-4xl font-black tracking-tighter text-glow uppercase leading-none">History</h1>
            <p className="mt-2 text-[10px] font-bold text-stone-500 uppercase tracking-widest">Your reading session history</p>
          </div>
          <a
            href="/admin/export/summary/"
            download
            className="py-1 text-[10px] font-bold uppercase tracking-widest text-stone-500 hover:text-stone-300 underline decoration-dotted underline-offset-4"
          >
            Export Summary
          </a>
        </header>
        <div className="text-center text-stone-500">No sessions yet</div>
      </div>
    )
  }

  const formatDate = (dateStr: string | null | undefined) => {
    if (!dateStr) return ''
    const date = new Date(dateStr)
    if (Number.isNaN(date.getTime())) return ''
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
  }

  const formatTime = (dateStr: string | null | undefined) => {
    if (!dateStr) return ''
    const date = new Date(dateStr)
    if (Number.isNaN(date.getTime())) return ''
    return date.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })
  }

  const formatDuration = (startedAt: string | null | undefined, endedAt: string | null | undefined) => {
    if (!startedAt || !endedAt) return null
    const start = new Date(startedAt)
    const end = new Date(endedAt)
    const diffMs = end.getTime() - start.getTime()
    if (!Number.isFinite(diffMs) || diffMs < 0) return null
    const diffMins = Math.floor(diffMs / 60000)
    const hours = Math.floor(diffMins / 60)
    const mins = diffMins % 60
    if (hours === 0) return `${mins}m`
    if (mins === 0) return `${hours}h`
    return `${hours}h ${mins}m`
  }

  const formatDiceProgression = (ladderPath: string | null | undefined) => {
    if (!ladderPath) return ''
    const dice = ladderPath.split(' → ')
    return dice.map(d => `d${d}`).join(' → ')
  }

  const buildActivityLine = (
    issuesRead: number | null | undefined,
    lastRating: number | null | undefined,
  ): string | null => {
    const parts: string[] = []
    if (issuesRead != null && issuesRead > 0) {
      parts.push(`${issuesRead} ${issuesRead === 1 ? 'issue' : 'issues'} read`)
    }
    if (lastRating != null) {
      parts.push(`rated ${lastRating.toFixed(1)}`)
    }
    return parts.length > 0 ? parts.join(' · ') : null
  }

  return (
    <div className="space-y-6 md:space-y-8 pb-20">
      <header className="flex flex-wrap items-end justify-between gap-3 px-2">
        <div>
          <h1 className="text-2xl md:text-4xl font-black tracking-tighter text-glow uppercase leading-none">History</h1>
          <p className="mt-2 text-[10px] font-bold text-stone-500 uppercase tracking-widest">Your reading session history</p>
        </div>
        <a
          href="/admin/export/summary/"
          download
          className="py-1 text-[10px] font-bold uppercase tracking-widest text-stone-500 hover:text-stone-300 underline decoration-dotted underline-offset-4"
        >
          Export Summary
        </a>
      </header>

      <div id="sessions-list" className="border-y border-[var(--theme-border)] divide-y divide-[var(--theme-border)]" role="list" aria-label="Session history">
        {sessions.map((session) => {
          const duration = formatDuration(session.started_at, session.ended_at)
          const isAbandonedRoll = (
            !session.active_thread
            && session.last_rolled_result == null
            && (session.snapshot_count ?? 0) <= 1
          )
          const activityLine = session.active_thread
            ? buildActivityLine(session.active_thread.issues_read, session.active_thread.last_rating)
            : null
          return (
            <div key={session.id} role="listitem" className="flex gap-3 md:gap-4 py-4 px-2 md:px-3">
              <div className="w-16 md:w-20 shrink-0">
                <div className="text-xs font-bold leading-none text-stone-200">
                  {formatDate(session.started_at)}
                </div>
                <div className="mt-1 text-[10px] font-bold uppercase tracking-widest leading-none text-stone-500">
                  {formatTime(session.started_at)}
                </div>
              </div>

              <div className="min-w-0 flex-1 space-y-1.5">
                {isAbandonedRoll ? (
                  <p className="text-sm font-bold text-[var(--theme-text-primary)]">
                    No issue selected
                  </p>
                ) : session.active_thread ? (
                  <>
                    <p className="font-bold text-sm leading-tight text-stone-200 truncate">
                      {session.active_thread.title}
                      {session.active_thread.next_issue_number ? (
                        <span className="text-stone-400"> · #{session.active_thread.next_issue_number}</span>
                      ) : null}
                    </p>
                    {activityLine ? (
                      <p className="text-xs text-stone-400">
                        {activityLine}
                      </p>
                    ) : (
                      <p className="text-[10px] font-bold text-stone-500 uppercase tracking-widest">
                        {session.active_thread.issues_remaining != null
                          ? `${session.active_thread.issues_remaining} left in queue`
                          : 'In progress'}
                      </p>
                    )}
                  </>
                ) : null}

                {session.ladder_path && (
                  <p className="text-[10px] font-bold uppercase tracking-widest text-stone-500">
                    Die size {formatDiceProgression(session.ladder_path)}
                    {session.last_rolled_result != null && session.last_rolled_result > 0 && (
                      <span className="text-amber-400/70"> · Rolled {session.last_rolled_result}</span>
                    )}
                  </p>
                )}

                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] font-bold text-stone-500 uppercase tracking-widest">
                  {duration && <span>Duration: {duration}</span>}
                  {(session.snapshot_count ?? 0) > 0 && (
                    <Link
                      to={`/sessions/${session.id}`}
                      className="underline decoration-dotted underline-offset-2 hover:text-stone-300"
                    >
                      Snapshots ({session.snapshot_count})
                    </Link>
                  )}
                  <Link
                    to={`/sessions/${session.id}`}
                    className="inline-flex items-center gap-1 text-stone-400 hover:text-stone-200 underline decoration-dotted underline-offset-4"
                  >
                    View full session <span aria-hidden>→</span>
                  </Link>
                </div>
              </div>
            </div>
          )
        })}
      </div>

      {isLoadingMore && (
        <div className="flex items-center justify-center py-8">
          <div className="text-sm font-bold text-stone-400 uppercase tracking-widest animate-pulse">
            Loading more...
          </div>
        </div>
      )}

      {error && !isLoadingMore && (
        <div className="text-center py-4">
          <p className="text-[10px] font-bold text-red-400 uppercase tracking-widest mb-3">
            Failed to load more sessions
          </p>
          <button
            onClick={loadMore}
            className="h-9 px-4 rounded-lg border border-[var(--theme-border)] text-xs font-bold text-[var(--theme-text-muted)] hover:text-[var(--theme-text-primary)] transition-colors"
          >
            Retry
          </button>
        </div>
      )}

      {hasMore && !isLoadingMore && (
        <div className="flex justify-center pt-4 pb-8">
          <button
            onClick={loadMore}
            className="h-10 md:h-12 px-6 md:px-8 rounded-lg border border-[var(--theme-border)] text-xs font-bold text-[var(--theme-text-muted)] hover:text-[var(--theme-text-primary)] transition-colors"
          >
            Load More Sessions
          </button>
        </div>
      )}
    </div>
  )
}
