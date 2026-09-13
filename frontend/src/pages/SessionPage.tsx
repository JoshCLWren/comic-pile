import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useSessionDetails, useSessionSnapshots, useRestoreSessionStart } from '../hooks/useSession'
import { useUndo } from '../hooks/useUndo'
import { formatDateTime } from '../utils/dateFormat'
import LoadingSpinner from '../components/LoadingSpinner'
import Modal from '../components/Modal'

type DisplayEvent = {
  id: number
  timestamp: string
  type: string
  thread_title?: string | null
  description?: string | null
  rating?: number | null
  result?: number | null
  die?: number | null
  queue_move?: string | null
  issues_read?: number | null
  die_after?: number | null
  selection_method?: string | null
  issue_number?: string | null
}

interface EventLabelMap extends Record<string, string> {}

const EVENT_LABELS: EventLabelMap = {
  roll: 'Rolled',
  rate: 'Rated',
  snooze: 'Snoozed',
  unsnooze: 'Unsnoozed',
  skip: 'Skipped',
  complete: 'Completed',
  completion: 'Completed',
  undo: 'Restored',
  restore: 'Restored',
  move: 'Moved',
  shuffle: 'Shuffled',
}

function eventLabel(type: string): string {
  return EVENT_LABELS[type] ?? type.replaceAll('_', ' ').replace(/^./, (letter) => letter.toUpperCase())
}

function EventRecord({ event }: { event: DisplayEvent }) {
  const metadata = [
    event.issues_read != null ? `${event.issues_read} ${event.issues_read === 1 ? 'issue' : 'issues'} read` : null,
    event.die != null ? `d${event.die}` : null,
    event.result != null ? `Rolled ${event.result}` : null,
    event.die_after != null ? `Die after: d${event.die_after}` : null,
    event.rating != null ? `Rating ${event.rating}` : null,
    event.selection_method ? `Selected by ${event.selection_method.replaceAll('_', ' ')}` : null,
  ].filter((value): value is string => value !== null)

  return (
    <article className="min-w-0 bg-white/5 border border-white/10 rounded-xl px-3 md:px-4 py-2.5 md:py-3">
      <div className="flex items-center gap-2 flex-wrap mb-2">
        <span className="text-[10px] font-bold uppercase tracking-widest text-stone-500">
          {formatDateTime(event.timestamp)}
        </span>
        <span className="text-[10px] font-black uppercase tracking-widest text-amber-500">
          {eventLabel(event.type)}
        </span>
      </div>
      <p className="min-w-0 break-words text-sm font-bold text-stone-200">
        {event.thread_title || 'Thread unavailable'}
        {event.thread_title && event.issue_number ? (
          <span className="text-stone-400"> · #{event.issue_number}</span>
        ) : null}
      </p>
      {metadata.length > 0 ? (
        <ul className="mt-2 flex min-w-0 flex-wrap gap-x-3 gap-y-1 text-xs text-stone-400" aria-label="Event details">
          {metadata.map((item) => (
            <li key={item} className="break-words">{item}</li>
          ))}
        </ul>
      ) : event.description ? (
        <p className="mt-1 text-xs text-stone-400 break-words">{event.description}</p>
      ) : (
        <p className="mt-1 text-xs text-stone-500">No additional event details recorded.</p>
      )}
      {event.queue_move && (
        <p className="mt-1 break-words text-xs text-stone-500">Queue move: {event.queue_move}</p>
      )}
    </article>
  )
}

export default function SessionPage() {
  const { id } = useParams()
  const { data: details, isPending, refetch: refetchDetails } = useSessionDetails(id)
  const { data: snapshotsData, refetch: refetchSnapshots } = useSessionSnapshots(id)
  const restoreMutation = useRestoreSessionStart()
  const undoMutation = useUndo()
  const [isRestoreConfirmationOpen, setIsRestoreConfirmationOpen] = useState(false)

  const snapshots = snapshotsData?.snapshots ?? []

  if (isPending) {
    return <LoadingSpinner fullScreen />
  }

  if (!details) {
    return <div className="text-center text-stone-500">Session not found</div>
  }

  const isEmptySession = details.events.length === 0

  return (
    <div className="space-y-6 md:space-y-8 pb-20">
      <header className="px-2">
        <h1 className="text-2xl md:text-4xl font-black tracking-tighter text-glow mb-1 uppercase">Session Details</h1>
        <p className="text-[10px] font-bold text-stone-500 uppercase tracking-widest">Session #{details.session_id}</p>
      </header>

      <div className="glass-card p-4 md:p-6 space-y-4 md:space-y-6">
        <div className="grid gap-3 md:gap-4 md:grid-cols-2">
          <div className="space-y-2">
            <p className="text-[10px] font-bold uppercase tracking-widest text-stone-500">Started</p>
            <p className="text-sm font-black text-stone-200">{formatDateTime(details.started_at)}</p>
          </div>
          <div className="space-y-2">
            <p className="text-[10px] font-bold uppercase tracking-widest text-stone-500">
              {details.ended_at ? 'Ended' : 'Status'}
            </p>
            <p className="text-sm font-black text-stone-200">
              {details.ended_at
                ? formatDateTime(details.ended_at)
                : isEmptySession
                  ? 'Abandoned roll'
                  : 'Active session'}
            </p>
          </div>
          <div className="space-y-2">
            <p className="text-[10px] font-bold uppercase tracking-widest text-stone-500">Start Die</p>
            <p className="text-sm font-black text-stone-200">d{details.start_die}</p>
          </div>
          <div className="space-y-2">
            <p className="text-[10px] font-bold uppercase tracking-widest text-stone-500">Current Die</p>
            <p className="text-sm font-black text-stone-200">d{details.current_die}</p>
          </div>
        </div>
        <div className="space-y-2">
          <p className="text-[10px] font-bold uppercase tracking-widest text-stone-500">Ladder Path</p>
          <p className="text-sm font-bold text-stone-300">{details.ladder_path}</p>
        </div>
        {isEmptySession && (
          <p className="rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] p-3 text-sm text-[var(--theme-text-muted)]">
            No reading activity was recorded for this roll.
          </p>
        )}
        <div className="grid gap-3 md:gap-4 md:grid-cols-3">
          {Object.entries(details.narrative_summary || {}).map(([key, values]) => (
            <div key={key} className="space-y-2 min-w-0">
              <p className="text-[10px] font-bold uppercase tracking-widest text-stone-500">{key}</p>
              {values && values.length > 0 ? (
                <ul className="space-y-1 text-xs text-stone-300">
                  {values.map((value) => (
                    <li key={value} className="break-words">{value}</li>
                  ))}
                </ul>
              ) : (
                <p className="text-xs text-stone-600">None</p>
              )}
            </div>
          ))}
        </div>
      </div>

      <div className="glass-card p-4 md:p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-black uppercase text-stone-200">Snapshots</h2>
          <button
            type="button"
            onClick={() => setIsRestoreConfirmationOpen(true)}
            disabled={restoreMutation.isPending || snapshots.length === 0}
            className="h-8 md:h-10 px-3 md:px-4 bg-white/5 border border-white/10 rounded-xl text-[10px] font-black uppercase tracking-widest text-stone-300 hover:bg-white/10 disabled:opacity-60"
          >
            {restoreMutation.isPending ? 'Restoring...' : 'Restore Start'}
          </button>
        </div>
        {snapshots.length === 0 ? (
          <p className="text-xs text-stone-500">No snapshots available.</p>
        ) : (
          <div className="space-y-3">
            {snapshots.map((snapshot, index) => {
              const canUndo = index === 0 && snapshot.description !== 'Session start'

              return (
                <div key={snapshot.id} className="flex items-center justify-between gap-2 md:gap-4 bg-white/5 border border-white/10 rounded-xl px-3 md:px-4 py-2.5 md:py-3">
                  <div className="min-w-0">
                    <p className="break-words text-xs md:text-sm font-bold text-stone-300">{snapshot.description || 'Snapshot'}</p>
                    <p className="text-[10px] font-bold uppercase tracking-widest text-stone-500">{formatDateTime(snapshot.created_at)}</p>
                  </div>
                  {canUndo ? (
                    <button
                      type="button"
                      onClick={async () => {
                        await undoMutation.mutate({
                          sessionId: details.session_id,
                          snapshotId: snapshot.id,
                        })
                        await Promise.all([refetchDetails(), refetchSnapshots()])
                      }}
                      disabled={undoMutation.isPending}
                      className="h-8 md:h-10 px-3 md:px-4 bg-white/5 border border-white/10 rounded-xl text-[10px] font-black uppercase tracking-widest text-stone-300 hover:bg-white/10 disabled:opacity-60 shrink-0"
                    >
                      Undo Latest
                    </button>
                  ) : (
                    <span className="text-[10px] font-black uppercase tracking-widest text-stone-600 shrink-0">
                      History
                    </span>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>

      <div className="glass-card p-4 md:p-6 space-y-4 min-w-0">
        <h2 className="text-lg font-black uppercase text-stone-200">Event Timeline</h2>
        {details.events.length === 0 ? (
          <p className="text-xs text-stone-500">
            No events to show. No reading activity was recorded for this roll.
          </p>
        ) : (
          <div className="space-y-3 min-w-0">
            {details.events.map((event) => (
              // SAFETY: the session details endpoint returns enriched events with the display-only fields beyond SessionEvent.
              <EventRecord key={event.id} event={event as DisplayEvent} />
            ))}
          </div>
        )}
      </div>

      <Modal
        isOpen={isRestoreConfirmationOpen}
        title="Restore session start?"
        onClose={() => setIsRestoreConfirmationOpen(false)}
        autoFocus={false}
      >
        <p className="text-sm text-[var(--theme-text-muted)]">
          This replaces your entire current pile with the state saved when Session #{details.session_id} began.
          Threads added since then may be removed, and reading progress, ratings, and queue order may be reverted.
        </p>
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <button
            type="button"
            onClick={() => setIsRestoreConfirmationOpen(false)}
            className="min-h-11 rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-4 text-sm font-bold text-[var(--theme-text-primary)]"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={async () => {
              await restoreMutation.mutate(details.session_id)
              setIsRestoreConfirmationOpen(false)
            }}
            disabled={restoreMutation.isPending}
            className="min-h-11 rounded-xl bg-[var(--theme-danger)] px-4 text-sm font-black text-[var(--theme-text-primary)] hover:bg-[var(--theme-danger-hover)] disabled:opacity-60"
          >
            {restoreMutation.isPending ? 'Restoring...' : 'Restore session start'}
          </button>
        </div>
      </Modal>
    </div>
  )
}
