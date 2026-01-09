import { useAnalytics } from '../hooks/useAnalytics'

export default function AnalyticsPage() {
  const { data: metrics, isLoading, error } = useAnalytics()

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-screen">
        <div className="text-slate-400">Loading analytics...</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-screen">
        <div className="text-red-400">Failed to load analytics data</div>
      </div>
    )
  }

  const formatTime = (timestamp) => {
    if (!timestamp) return 'N/A'
    return new Date(timestamp).toLocaleTimeString('en-US', {
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  return (
    <div className="space-y-6 pb-10">
      <header className="flex justify-between items-center px-2">
        <div>
          <h1 className="text-4xl font-black tracking-tighter text-glow mb-1 uppercase">
            Analytics
          </h1>
          <p className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">
            Task completion metrics and system health
          </p>
        </div>
      </header>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="glass-card p-4">
          <div className="text-3xl font-bold text-teal-400">{metrics.total_tasks}</div>
          <div className="text-xs text-slate-400 uppercase tracking-widest mt-1">Total Tasks</div>
        </div>
        <div className="glass-card p-4">
          <div className="text-3xl font-bold text-emerald-400">{metrics.completion_rate}%</div>
          <div className="text-xs text-slate-400 uppercase tracking-widest mt-1">Completion Rate</div>
        </div>
        <div className="glass-card p-4">
          <div className="text-3xl font-bold text-sky-400">{metrics.ready_to_claim}</div>
          <div className="text-xs text-slate-400 uppercase tracking-widest mt-1">Ready to Claim</div>
        </div>
        <div className="glass-card p-4">
          <div className="text-3xl font-bold text-amber-400">
            {metrics.average_completion_time_hours ? `${metrics.average_completion_time_hours}h` : 'N/A'}
          </div>
          <div className="text-xs text-slate-400 uppercase tracking-widest mt-1">Avg Completion</div>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        <div className="glass-card p-4">
          <h3 className="text-sm font-black uppercase tracking-widest text-slate-300 mb-3">Tasks by Status</h3>
          <div className="space-y-2">
            {Object.entries(metrics.tasks_by_status).map(([status, count]) => (
              <div key={status} className="flex items-center justify-between">
                <span className="text-xs text-slate-400 capitalize">
                  {status.replace('_', ' ')}
                </span>
                <span
                  className={`text-sm font-bold ${
                    status === 'done'
                      ? 'text-emerald-400'
                      : status === 'in_progress'
                        ? 'text-amber-400'
                        : status === 'blocked'
                          ? 'text-rose-400'
                          : status === 'in_review'
                            ? 'text-sky-400'
                            : 'text-slate-300'
                  }`}
                >
                  {count}
                </span>
              </div>
            ))}
          </div>
        </div>

        <div className="glass-card p-4">
          <h3 className="text-sm font-black uppercase tracking-widest text-slate-300 mb-3">Tasks by Priority</h3>
          <div className="space-y-2">
            {Object.entries(metrics.tasks_by_priority).map(([priority, count]) => (
              <div key={priority} className="flex items-center justify-between">
                <span className="text-xs text-slate-400">{priority}</span>
                <span
                  className={`text-sm font-bold ${
                    priority === 'HIGH'
                      ? 'text-rose-400'
                      : priority === 'MEDIUM'
                        ? 'text-amber-400'
                        : 'text-slate-300'
                  }`}
                >
                  {count}
                </span>
              </div>
            ))}
          </div>
        </div>

        <div className="glass-card p-4">
          <h3 className="text-sm font-black uppercase tracking-widest text-slate-300 mb-3">Tasks by Type</h3>
          <div className="space-y-2">
            {Object.entries(metrics.tasks_by_type).map(([type, count]) => (
              <div key={type} className="flex items-center justify-between">
                <span className="text-xs text-slate-400 capitalize">{type.replace('_', ' ')}</span>
                <span className="text-sm font-bold text-slate-300">{count}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="glass-card p-4">
          <h3 className="text-sm font-black uppercase tracking-widest text-slate-300 mb-3">System Health</h3>
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-xs text-slate-400">Stale Tasks (&gt;20m)</span>
              <span
                className={`text-sm font-bold ${metrics.stale_tasks_count > 0 ? 'text-rose-400' : 'text-emerald-400'}`}
              >
                {metrics.stale_tasks_count}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-xs text-slate-400">Blocked Tasks</span>
              <span
                className={`text-sm font-bold ${metrics.blocked_tasks_count > 0 ? 'text-amber-400' : 'text-slate-300'}`}
              >
                {metrics.blocked_tasks_count}
              </span>
            </div>
          </div>
        </div>

        <div className="glass-card p-4">
          <h3 className="text-sm font-black uppercase tracking-widest text-slate-300 mb-3">Active Agents</h3>
          {metrics.active_agents && metrics.active_agents.length > 0 ? (
            <div className="space-y-2">
              {metrics.active_agents.map((agent) => (
                <div key={agent.agent_name} className="bg-white/5 rounded-lg p-3">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold text-slate-200">{agent.agent_name}</span>
                    <span className="text-[10px] px-2 py-1 rounded bg-amber-500/20 text-amber-400 uppercase tracking-widest">
                      {agent.active_tasks} task{agent.active_tasks !== 1 ? 's' : ''}
                    </span>
                  </div>
                  {agent.task_ids && agent.task_ids.length > 0 && (
                    <div className="mt-2 text-[10px] text-slate-500 font-mono">
                      {agent.task_ids.join(', ')}
                    </div>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <p className="text-xs text-slate-500">No active agents</p>
          )}
        </div>
      </div>

      <div className="glass-card p-4">
        <h3 className="text-sm font-black uppercase tracking-widest text-slate-300 mb-3">Recent Completions</h3>
        {metrics.recent_completions && metrics.recent_completions.length > 0 ? (
          <div className="space-y-2">
            {metrics.recent_completions.map((completion) => (
              <div key={completion.task_id} className="bg-white/5 rounded-lg p-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-[10px] font-mono text-teal-400">{completion.task_id}</span>
                      <span className="text-[10px] px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-400 uppercase tracking-widest">
                        Done
                      </span>
                    </div>
                    <p className="text-sm font-medium text-slate-200 truncate">{completion.title}</p>
                    <p className="text-[10px] text-slate-500 mt-1">By: {completion.completed_by}</p>
                  </div>
                  <div className="text-[10px] text-slate-400 whitespace-nowrap">
                    {formatTime(completion.completed_at)}
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-xs text-slate-500">No recent completions</p>
        )}
      </div>
    </div>
  )
}