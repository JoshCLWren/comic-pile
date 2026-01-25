import { useAnalytics } from '../hooks/useAnalytics'
import { formatTime24 } from '../utils/dateFormat'
import LoadingSpinner from '../components/LoadingSpinner'

export default function AnalyticsPage() {
  const { data: metrics, isLoading, error } = useAnalytics()

  if (isLoading) {
    return <LoadingSpinner fullScreen message="Loading analytics..." />
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-screen">
        <div className="text-red-400">Failed to load analytics data</div>
      </div>
    )
  }

  return (
    <div className="space-y-6 pb-10">
      <header className="flex justify-between items-center px-2">
        <div>
          <h1 className="text-4xl font-black tracking-tighter text-glow mb-1 uppercase">
            Analytics
          </h1>
          <p className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">
            Comic reading metrics and engagement stats
          </p>
        </div>
      </header>

      {/* Top Metrics Cards */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        <div className="glass-card p-4">
          <div className="text-3xl font-bold text-teal-400">{metrics.total_threads || 0}</div>
          <div className="text-xs text-slate-400 uppercase tracking-widest mt-1">Total Threads</div>
        </div>
        <div className="glass-card p-4">
          <div className="text-3xl font-bold text-sky-400">{metrics.active_threads || 0}</div>
          <div className="text-xs text-slate-400 uppercase tracking-widest mt-1">Active Threads</div>
        </div>
        <div className="glass-card p-4">
          <div className="text-3xl font-bold text-emerald-400">{metrics.completed_threads || 0}</div>
          <div className="text-xs text-slate-400 uppercase tracking-widest mt-1">Completed</div>
        </div>
        <div className="glass-card p-4">
          <div className="text-3xl font-bold text-purple-400">
            {Number.isFinite(metrics.completion_rate) 
              ? `${metrics.completion_rate.toFixed(1)}%` 
              : 'N/A'}
          </div>
          <div className="text-xs text-slate-400 uppercase tracking-widest mt-1">Completion Rate</div>
        </div>
        <div className="glass-card p-4">
          <div className="text-3xl font-bold text-amber-400">
            {Number.isFinite(metrics.average_session_hours)
              ? `${metrics.average_session_hours.toFixed(1)}h`
              : 'N/A'}
          </div>
          <div className="text-xs text-slate-400 uppercase tracking-widest mt-1">Avg Session</div>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Recent Sessions */}
        <div className="glass-card p-4">
          <h3 className="text-sm font-black uppercase tracking-widest text-slate-300 mb-3">Recent Sessions</h3>
          {metrics.recent_sessions && metrics.recent_sessions.length > 0 ? (
            <div className="space-y-2">
              {metrics.recent_sessions.slice(0, 5).map((session) => (
                <div key={session.id} className="bg-white/5 rounded-lg p-3">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-[10px] font-mono text-teal-400">Session #{session.id}</span>
                    <span className="text-[10px] px-2 py-0.5 rounded bg-purple-500/20 text-purple-400 uppercase tracking-widest">
                      Die {session.start_die}
                    </span>
                  </div>
                  <div className="flex items-center justify-between text-[10px]">
                    <span className="text-slate-400">Started:</span>
                    <span className="text-slate-300">{formatTime24(session.started_at)}</span>
                  </div>
                  {session.ended_at && (
                    <div className="flex items-center justify-between text-[10px] mt-1">
                      <span className="text-slate-400">Ended:</span>
                      <span className="text-slate-300">{formatTime24(session.ended_at)}</span>
                    </div>
                  )}
                  {!session.ended_at && (
                    <div className="mt-1">
                      <span className="text-[10px] px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-400 uppercase tracking-widest">
                        Active
                      </span>
                    </div>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <p className="text-xs text-slate-500">No recent sessions</p>
          )}
        </div>

        {/* Event Stats */}
        <div className="glass-card p-4">
          <h3 className="text-sm font-black uppercase tracking-widest text-slate-300 mb-3">Event Statistics</h3>
          {metrics.event_stats && Object.keys(metrics.event_stats).length > 0 ? (
            <div className="space-y-2">
              {Object.entries(metrics.event_stats).map(([eventType, count]) => (
                <div key={eventType} className="flex items-center justify-between">
                  <span className="text-xs text-slate-400 capitalize">
                    {eventType.replace('_', ' ')}
                  </span>
                  <span
                    className={`text-sm font-bold ${
                      eventType === 'roll'
                        ? 'text-teal-400'
                        : eventType === 'rate'
                          ? 'text-amber-400'
                          : eventType === 'undo'
                            ? 'text-rose-400'
                            : 'text-slate-300'
                    }`}
                  >
                    {count}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-xs text-slate-500">No event data available</p>
          )}
        </div>
      </div>

      {/* Top Rated Comics */}
      <div className="glass-card p-4">
        <h3 className="text-sm font-black uppercase tracking-widest text-slate-300 mb-3">Top Rated Comics</h3>
        {metrics.top_rated_threads && metrics.top_rated_threads.length > 0 ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {metrics.top_rated_threads.map((thread) => (
              <div key={thread.id} className="bg-white/5 rounded-lg p-3">
                <div className="flex items-start justify-between gap-2 mb-2">
                  <h4 className="text-sm font-bold text-slate-200 line-clamp-2 flex-1">
                    {thread.title}
                  </h4>
                  <div className="flex items-center gap-1 shrink-0">
                    <span className="text-amber-400 text-sm">★</span>
                    <span className="text-sm font-bold text-amber-400">
                      {Number.isFinite(thread.rating) ? thread.rating.toFixed(1) : 'N/A'}
                    </span>
                  </div>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-[10px] font-mono text-teal-400">#{thread.id}</span>
                  <span className="text-[10px] px-2 py-0.5 rounded bg-sky-500/20 text-sky-400 uppercase tracking-widest">
                    {thread.format || 'Unknown'}
                  </span>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-xs text-slate-500">No rated comics yet</p>
        )}
      </div>
    </div>
  )
}