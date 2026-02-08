import { useSessions } from '../hooks/useSession'
import { Link } from 'react-router-dom'

export default function HistoryPage() {
  const { data: sessions, isLoading, error } = useSessions()

  if (isLoading) {
    return <div className="flex items-center justify-center h-screen">Loading...</div>
  }

  if (error) {
    return <div className="error-message">Failed to load sessions</div>
  }

  if (!sessions || sessions.length === 0) {
    return (
      <div className="space-y-8 pb-20">
        <header className="px-2">
          <div className="flex items-center gap-4">
            <h1 className="text-4xl font-black tracking-tighter text-glow mb-1 uppercase">History</h1>
            <a href="/admin/export/summary/"
               className="h-10 px-4 glass-button text-[10px] font-black uppercase tracking-widest whitespace-nowrap shadow-xl"
               download>
              Export Summary
            </a>
          </div>
          <p className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">Your reading session history</p>
        </header>
        <div className="text-center text-slate-500">No sessions yet</div>
      </div>
    )
  }

  const formatDate = (dateStr) => {
    if (!dateStr) return ''
    const date = new Date(dateStr)
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
  }

  const formatTime = (dateStr) => {
    if (!dateStr) return ''
    const date = new Date(dateStr)
    return date.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })
  }

  const formatDuration = (startedAt, endedAt) => {
    if (!startedAt) return ''
    const start = new Date(startedAt)
    const end = endedAt ? new Date(endedAt) : new Date()
    const diffMs = end - start
    const diffMins = Math.floor(diffMs / 60000)
    const hours = Math.floor(diffMins / 60)
    const mins = diffMins % 60
    if (hours === 0) return `${mins}m`
    if (mins === 0) return `${hours}h`
    return `${hours}h ${mins}m`
  }

  const formatDiceProgression = (ladderPath) => {
    if (!ladderPath) return ''
    const dice = ladderPath.split(' → ')
    return dice.map(d => `d${d}`).join(' → ')
  }

  return (
    <div className="space-y-8 pb-20">
      <header className="px-2">
        <div className="flex items-center gap-4">
          <h1 className="text-4xl font-black tracking-tighter text-glow mb-1 uppercase">History</h1>
          <a href="/admin/export/summary/"
             className="h-10 px-4 glass-button text-[10px] font-black uppercase tracking-widest whitespace-nowrap shadow-xl"
             download>
            Export Summary
          </a>
        </div>
        <p className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">Your reading session history</p>
      </header>

      <div id="sessions-list" className="space-y-4" role="list" aria-label="Session history">
        {sessions.map((session) => (
          <div key={session.id} role="listitem" className="glass-card p-6 group transition-all hover:border-white/20 relative overflow-hidden">
            <div className="flex justify-between items-start gap-6 relative z-10">
              <div className="space-y-4 flex-1 min-w-0">
                <div className="flex items-center gap-3">
                  <div className="px-2 py-0.5 bg-white/5 rounded-lg border border-white/5 text-[9px] font-black uppercase tracking-widest text-slate-400">
                    {formatDate(session.started_at)}
                  </div>
                  <span className="text-[9px] font-bold uppercase tracking-widest text-slate-600">
                    {formatTime(session.started_at)}
                  </span>
                </div>

                {session.ladder_path && (
                  <div className="space-y-2">
                    <p className="text-sm font-black text-slate-300">
                      Dice progression: {formatDiceProgression(session.ladder_path)}
                    </p>
                  </div>
                )}

                {session.active_thread && (
                  <div className="text-sm space-y-1">
                    <p className="font-black text-slate-300 truncate">{session.active_thread.title}</p>
                    <p className="text-[8px] font-black text-slate-500 uppercase tracking-widest">{session.active_thread.format}</p>
                    {session.last_rolled_result !== null && session.last_rolled_result !== undefined && (
                      <p className="text-[9px] font-black text-teal-300 uppercase tracking-widest">
                        Rolled: {session.last_rolled_result} of d{session.current_die}
                      </p>
                    )}
                    <div className="flex items-center gap-3 text-[9px] font-black text-slate-500 uppercase tracking-widest">
                      <span>Duration: {formatDuration(session.started_at, session.ended_at)}</span>
                      <span>·</span>
                      <span>Comics read: {session.snapshot_count}</span>
                    </div>
                  </div>
                )}
              </div>

              <div className="flex gap-2">
                <Link
                  to={`/sessions/${session.id}`}
                  className="h-12 px-6 glass-button text-xs font-black uppercase tracking-widest whitespace-nowrap shadow-xl"
                >
                  View Full Session
                </Link>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
