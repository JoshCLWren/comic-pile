import { useMemo } from 'react'
import type { Dependency, Thread } from '../types'
import {
  buildReadingOrderTimelineEntries,
  type GateStatus,
  type TimelineEntry,
  type TimelineGateEntry,
  type TimelineSpanEntry,
} from '../utils/readingOrderTimeline'

interface Props {
  thread: Thread | null
  dependencies: Dependency[]
}

const STATUS_STYLES: Record<GateStatus, { label: string; classes: string; description: string }> = {
  blocked: {
    label: 'Blocked',
    description: 'Read prerequisite to continue',
    classes: 'bg-red-500/10 text-red-300 border-red-500/40',
  },
  satisfied: {
    label: 'Satisfied',
    description: 'Gate cleared',
    classes: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/40',
  },
  dormant: {
    label: 'Dormant',
    description: 'Future gate',
    classes: 'bg-amber-500/10 text-amber-200 border-amber-500/40',
  },
}

export default function ReadingOrderTimeline({ thread, dependencies }: Props) {
  const issueTimeline = useMemo<TimelineEntry[]>(() => {
    if (!thread) {
      return []
    }
    return buildReadingOrderTimelineEntries({ thread, dependencies })
  }, [thread, dependencies])

  if (!thread) {
    return (
      <div className="rounded-2xl border border-white/10 bg-white/5 p-4 text-sm text-stone-400">
        Select a thread to see its reading order.
      </div>
    )
  }

  const nextIssueLabel = thread.issues_remaining === 0
    ? 'Completed'
    : thread.next_unread_issue_number
      ? `Issue #${thread.next_unread_issue_number}`
      : 'Unknown'

  if (issueTimeline.length === 0) {
    return (
      <div className="rounded-2xl border border-white/10 bg-white/5 p-4 text-sm text-stone-300">
        No issue-level dependencies yet. Issues 1–{thread.total_issues ?? '…'} are clear to read straight through.
      </div>
    )
  }

  return (
    <div className="rounded-3xl border border-white/10 bg-white/5 backdrop-blur-sm p-4 space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] font-black uppercase tracking-widest text-stone-400">
        <span>Reading Position</span>
        <span className="text-white">{nextIssueLabel}</span>
      </div>
      {thread.total_issues === null && (
        <div className="rounded-2xl border border-amber-500/30 bg-amber-500/10 p-3 text-[11px] font-semibold uppercase tracking-widest text-amber-200">
          Reading order will be more precise after migrating this thread to per-issue tracking.
        </div>
      )}
      <div className="mt-3 max-h-[50vh] space-y-3 overflow-y-auto pr-1">
        {issueTimeline.map((entry) =>
          entry.kind === 'gate' ? (
            <GateCard key={`gate-${entry.gate.id}`} gate={entry.gate} />
          ) : (
            <SpanCard key={entry.span.id} span={entry.span} />
          ),
        )}
      </div>
    </div>
  )
}

function GateCard({ gate }: { gate: TimelineGateEntry }) {
  const statusMeta = STATUS_STYLES[gate.status]
  return (
    <div className="rounded-2xl border border-white/10 bg-stone-950/40 p-3 text-sm text-stone-200 shadow-inner">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-base font-semibold text-white">Issue #{gate.issueNumberText ?? '??'}</p>
          <p className="text-xs text-stone-400">{gate.targetLabel}</p>
        </div>
        <span className={`rounded-full border px-2 py-0.5 text-[11px] font-black uppercase tracking-wide ${statusMeta.classes}`}>
          {statusMeta.label}
        </span>
      </div>
      <p className="mt-3 text-xs text-stone-300">
        <span className="font-semibold text-white">Prerequisite:</span> {gate.prerequisiteLabel}
      </p>
      <p className="mt-1 text-[11px] uppercase tracking-widest text-stone-500">{statusMeta.description}</p>
      {gate.isCurrent && (
        <div className="mt-2 inline-flex items-center gap-1 rounded-full bg-blue-500/10 px-2 py-0.5 text-[11px] font-black uppercase tracking-widest text-blue-300">
          <span aria-hidden="true">📍</span>
          Current position
        </div>
      )}
    </div>
  )
}

function SpanCard({ span }: { span: TimelineSpanEntry }) {
  return (
    <div className="rounded-2xl border border-white/5 bg-white/5 p-3 text-sm text-stone-200">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-base font-semibold text-white">{span.label}</p>
          <p className="text-xs text-stone-400">No dependency gates in this range</p>
        </div>
        {span.isCurrent && (
          <span className="rounded-full bg-blue-500/10 px-2 py-0.5 text-[11px] font-black uppercase tracking-widest text-blue-300">
            You are here
          </span>
        )}
      </div>
    </div>
  )
}
