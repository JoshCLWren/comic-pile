import React from 'react'
import { useParams } from 'react-router-dom'
import { useSessionDetails, useSessionSnapshots, useRestoreSessionStart } from '../hooks/useSession'
import { useUndo } from '../hooks/useUndo'
import { formatDateTime } from '../utils/dateFormat'
import LoadingSpinner from '../components/LoadingSpinner'
import type { SessionDetails, SessionEvent } from '../services/api'

interface Snapshot {
  id: number
  description: string | null
  created_at: string
}

export default function SessionPage(): React.JSX.Element {
  const { id } = useParams<{ id: string }>()
  const sessionId = id ? parseInt(id, 10) : undefined
  const { data: details, isPending } = useSessionDetails(sessionId)
  const { data: snapshotsData } = useSessionSnapshots(sessionId)
  const restoreMutation = useRestoreSessionStart()
  const undoMutation = useUndo()

  const snapshots: Snapshot[] = Array.isArray(snapshotsData) ? snapshotsData.map(s => ({
    id: s.id,
    description: s.action,
    created_at: s.timestamp
  })) : []

  if (isPending) {
    return <LoadingSpinner fullScreen />
  }

  if (!details) {
    return <div className="text-center text-slate-500">Session not found</div>
  }

  return (
    <div className="space-y-8 pb-20">
      <header className="px-2">
        <h1 className="text-4xl font-black tracking-tighter text-glow mb-1 uppercase">Session Details</h1>
        <p className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">Session #{details.session_id}</p>
      </header>

      <div className="glass-card p-6 space-y-6">
        <div className="grid gap-4 md:grid-cols-2">
          <div className="space-y-2">
            <p className="text-[10px] font-bold uppercase tracking-widest text-slate-500">Started</p>
            <p className="text-sm font-black text-slate-100">{formatDateTime(details.started_at)}</p>
          </div>
          <div className="space-y-2">
            <p className="text-[10px] font-bold uppercase tracking-widest text-slate-500">Ended</p>
            <p className="text-sm font-black text-slate-100">
              {details.ended_at ? formatDateTime(details.ended_at) : 'Active'}
            </p>
          </div>
          <div className="space-y-2">
            <p className="text-[10px] font-bold uppercase tracking-widest text-slate-500">Start Die</p>
            <p className="text-sm font-black text-slate-100">d{details.start_die}</p>
          </div>
          <div className="space-y-2">
            <p className="text-[10px] font-bold uppercase tracking-widest text-slate-500">Current Die</p>
            <p className="text-sm font-black text-slate-100">d{details.current_die}</p>
          </div>
        </div>
        <div className="space-y-2">
          <p className="text-[10px] font-bold uppercase tracking-widest text-slate-500">Ladder Path</p>
          <p className="text-sm font-bold text-slate-300">{details.ladder_path}</p>
        </div>
        <div className="grid gap-4 md:grid-cols-3">
          {Object.entries(details.narrative_summary || {}).map(([key, values]: [string, string[]]) => (
            <div key={key} className="space-y-2">
              <p className="text-[10px] font-bold uppercase tracking-widest text-slate-500">{key}</p>
              {values && values.length > 0 ? (
                <ul className="space-y-1 text-xs text-slate-300">
                  {values.map((value: string) => (
                    <li key={value}>{value}</li>
                  ))}
                </ul>
              ) : (
                <p className="text-xs text-slate-600">None</p>
              )}
            </div>
          ))}
        </div>
      </div>

      <div className="glass-card p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-black uppercase text-slate-100">Snapshots</h2>
          <button
            type="button"
            onClick={() => restoreMutation.mutate(details.session_id)}
            disabled={restoreMutation.isPending || snapshots.length === 0}
            className="h-10 px-4 bg-white/5 border border-white/10 rounded-xl text-[10px] font-black uppercase tracking-widest text-slate-300 hover:bg-white/10 disabled:opacity-60"
          >
            {restoreMutation.isPending ? 'Restoring...' : 'Restore Start'}
          </button>
        </div>
        {snapshots.length === 0 ? (
          <p className="text-xs text-slate-500">No snapshots available.</p>
        ) : (
          <div className="space-y-3">
            {snapshots.map((snapshot: Snapshot) => (
              <div key={snapshot.id} className="flex items-center justify-between gap-4 bg-white/5 border border-white/10 rounded-xl px-4 py-3">
                <div>
                  <p className="text-sm font-bold text-slate-200">{snapshot.description || 'Snapshot'}</p>
                  <p className="text-[10px] font-bold uppercase tracking-widest text-slate-500">{formatDateTime(snapshot.created_at)}</p>
                </div>
                <button
                  type="button"
                  onClick={() =>
                    undoMutation.mutate({ sessionId: details.session_id, snapshotId: snapshot.id })
                  }
                  disabled={undoMutation.isPending}
                  className="h-10 px-4 bg-white/5 border border-white/10 rounded-xl text-[10px] font-black uppercase tracking-widest text-slate-300 hover:bg-white/10 disabled:opacity-60"
                >
                  Undo
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="glass-card p-6 space-y-4">
        <h2 className="text-lg font-black uppercase text-slate-100">Event Timeline</h2>
        {details.events.length === 0 ? (
          <p className="text-xs text-slate-500">No events recorded.</p>
        ) : (
          <div className="space-y-3">
            {details.events.map((event: SessionEvent) => (
              <div key={event.id} className="bg-white/5 border border-white/10 rounded-xl px-4 py-3">
                <div className="flex items-center gap-2 flex-wrap mb-1">
                  <span className="text-[10px] font-bold uppercase tracking-widest text-slate-500">
                    {formatDateTime(event.timestamp)}
                  </span>
                  <span className="text-[10px] font-black uppercase tracking-widest text-teal-400">{event.type}</span>
                </div>
                <p className="text-sm text-slate-200">
                  {event.thread_title || 'Thread'}
                  {event.rating ? ` • Rated ${event.rating}` : ''}
                  {event.result ? ` • Rolled ${event.result}` : ''}
                  {event.die ? ` • d${event.die}` : ''}
                </p>
                {event.queue_move && (
                  <p className="text-xs text-slate-500">Queue move: {event.queue_move}</p>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
