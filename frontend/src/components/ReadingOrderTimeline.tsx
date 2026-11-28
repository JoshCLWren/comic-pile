import { useMemo } from 'react'
import type { Dependency, Thread, ThreadListItem } from '../types'
import CompactIssueCardTrigger from './CompactIssueCardTrigger'
import { useIssueCards, indexIssueCards } from '../hooks/useIssueCards'
import type { IssueCard } from '../services/issueCardsApi'
import {
  buildReadingOrderTimelineEntries,
  type GateStatus,
  type TimelineEntry,
  type TimelineGateEntry,
  type TimelineSpanEntry,
} from '../utils/readingOrderTimeline'

interface Props {
  thread: Thread | ThreadListItem | null
  dependencies: Dependency[]
}

const STATUS_STYLES: Record<GateStatus, { label: string; classes: string; description: string }> = {
  blocked: {
    label: 'Blocked',
    description: 'Read prerequisite to continue',
    classes: 'bg-[var(--theme-warning)]/10 text-[var(--theme-warning)] border-[var(--theme-warning)]/40',
  },
  satisfied: {
    label: 'Satisfied',
    description: 'Gate cleared',
    classes: 'bg-[var(--theme-success)]/10 text-[var(--theme-success)] border-[var(--theme-success)]/40',
  },
  dormant: {
    label: 'Dormant',
    description: 'Future gate',
    classes: 'bg-[var(--theme-comic-accent)]/10 text-[var(--theme-comic-accent)] border-[var(--theme-comic-accent)]/40',
  },
}

export default function ReadingOrderTimeline({ thread, dependencies }: Props) {
  const issueTimeline = useMemo<TimelineEntry[]>(() => {
    if (!thread) {
      return []
    }
    return buildReadingOrderTimelineEntries({ thread, dependencies })
  }, [thread, dependencies])
  const cards = useIssueCards(issueTimeline.flatMap((entry) =>
    entry.kind === 'gate' ? [entry.gate.targetIssueId] : [],
  ))
  const cardsByIssue = indexIssueCards(cards.data)

  if (!thread) {
    return (
      <div className="rounded-2xl border border-[var(--theme-border)] bg-[var(--theme-bg-hover)] p-4 text-sm text-[var(--theme-text-muted)]">
        Select a thread to see its reading order.
      </div>
    )
  }

  const nextIssueLabel = thread.issues_remaining === 0
    ? 'Completed'
    : thread.next_unread_issue_number
      ? `Issue #${thread.next_unread_issue_number}`
      : 'Unknown'

  return (
    <div className="rounded-3xl border border-[var(--theme-border)] bg-[var(--theme-bg-hover)] surface-panel p-4 space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] font-black uppercase tracking-widest text-[var(--theme-text-muted)]">
        <span>Reading Position</span>
        <span className="text-[var(--theme-text-primary)]">{nextIssueLabel}</span>
      </div>
      {thread.total_issues == null && (
        <div className="rounded-2xl border border-[var(--theme-comic-accent)]/30 bg-[var(--theme-comic-accent)]/10 p-3 text-[11px] font-semibold uppercase tracking-widest text-[var(--theme-comic-accent)]">
          Reading order will be more precise after migrating this thread to per-issue tracking.
        </div>
      )}
      <div className="mt-3 max-h-[50vh] space-y-3 overflow-y-auto pr-1">
        {issueTimeline.map((entry) =>
          entry.kind === 'gate' ? (
            <GateCard key={`gate-${entry.gate.targetIssueId}`} gate={entry.gate} card={cardsByIssue.get(entry.gate.targetIssueId)} />
          ) : (
            <SpanCard key={entry.span.id} span={entry.span} />
          ),
        )}
      </div>
    </div>
  )
}

function GateCard({ gate, card }: { gate: TimelineGateEntry; card?: IssueCard }) {
  const statusMeta = STATUS_STYLES[gate.status]
  const prerequisiteCount = gate.prerequisiteLabels.length
  return (
    <div className="rounded-2xl border border-[var(--theme-border)] bg-[var(--theme-bg-page)]/40 p-3 text-sm text-[var(--theme-text-primary)] shadow-inner">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          {card ? (
            <CompactIssueCardTrigger
              issueId={gate.targetIssueId}
              card={card}
              threadTitle={card.thread_title}
              issueNumber={card.issue_number}
            />
          ) : (
            <>
              <p className="text-base font-semibold text-[var(--theme-text-primary)]">
                Issue #{gate.issueNumberText ?? gate.targetIssueId}
              </p>
              <p className="text-xs text-[var(--theme-text-muted)]">{gate.targetLabel}</p>
            </>
          )}
        </div>
        <span className={`rounded-full border px-2 py-0.5 text-[11px] font-black uppercase tracking-wide ${statusMeta.classes}`}>
          {statusMeta.label}
        </span>
      </div>
      <p className="mt-3 text-xs text-[var(--theme-text-primary)]">
        <span className="font-semibold text-[var(--theme-text-primary)]">
          {prerequisiteCount === 1 ? 'Prerequisite:' : 'Prerequisites:'}
        </span>{' '}
        {prerequisiteCount === 1
          ? gate.prerequisiteLabels[0]
          : `${prerequisiteCount} required`}
      </p>
      <p className="mt-1 text-[11px] uppercase tracking-widest text-[var(--theme-text-dim)]">{statusMeta.description}</p>
      {gate.isCurrent && (
        <div className="mt-2 inline-flex items-center gap-1 rounded-full bg-[var(--theme-continuity-accent)]/10 px-2 py-0.5 text-[11px] font-black uppercase tracking-widest text-[var(--theme-continuity-accent)]">
          <span aria-hidden="true">📍</span>
          Current position
        </div>
      )}
    </div>
  )
}

function SpanCard({ span }: { span: TimelineSpanEntry }) {
  return (
    <div className="rounded-2xl border border-[var(--theme-border)] bg-[var(--theme-bg-hover)] p-3 text-sm text-[var(--theme-text-primary)]">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-base font-semibold text-[var(--theme-text-primary)]">{span.label}</p>
          <p className="text-xs text-[var(--theme-text-muted)]">No dependency gates in this range</p>
        </div>
        {span.isCurrent && (
          <span className="rounded-full bg-[var(--theme-continuity-accent)]/10 px-2 py-0.5 text-[11px] font-black uppercase tracking-widest text-[var(--theme-continuity-accent)]">
            You are here
          </span>
        )}
      </div>
    </div>
  )
}
