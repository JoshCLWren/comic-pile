import { useMemo } from 'react'
import type { ReaderContextEdge, ReaderContextResponse } from '../../../types'
import {
  buildPrerequisiteLanes,
  classifyEdgesRelativeToCurrent,
} from '../readingPath'
import type { ContinuityReadinessState } from '../../../hooks/useContinuityReadiness'
import { readingContextType } from '../readingContextTypography'

interface ReadingPathPanelProps {
  context: ReaderContextResponse
  readinessState: ContinuityReadinessState
  /** Human label for the active issue, used when series identity is unavailable. */
  fallbackAnchorLabel: string
  onOpenThread: (threadId: number) => void
}

function EdgeEndpoint({
  label,
  threadId,
  onOpen,
}: {
  label: string | null
  threadId: number | null
  onOpen: (threadId: number) => void
}) {
  const endpointStyle = readingContextType('primaryValue')
  if (threadId === null) {
    return (
      <span className="min-w-0 break-words font-mono text-[var(--theme-text-primary)]" style={endpointStyle}>
        {label ?? 'a missing issue'}
      </span>
    )
  }
  return (
    <button
      type="button"
      className="inline-flex min-h-6 items-center break-words text-left font-mono underline decoration-dotted underline-offset-2 text-[var(--theme-text-primary)]"
      style={endpointStyle}
      onClick={() => onOpen(threadId)}
      aria-label={`Open thread for ${label ?? 'a missing issue'}`}
    >
      {label ?? 'a missing issue'}
    </button>
  )
}

function StepStateMark({ status }: { status: string | null }) {
  if (status === 'read') {
    return (
      <span className="whitespace-nowrap font-bold text-emerald-400" style={readingContextType('metaLabel')}>
        Already read
      </span>
    )
  }
  if (status === 'unread') {
    return (
      <span className="whitespace-nowrap font-bold text-amber-300" style={readingContextType('metaLabel')}>
        Not read yet
      </span>
    )
  }
  return null
}

export function ReadingPathPanel({
  context,
  readinessState,
  fallbackAnchorLabel,
  onOpenThread,
}: ReadingPathPanelProps) {
  const seriesName = context.series.series_name
  const currentIssue = useMemo(
    () => context.local_chain.issues.find((issue) => issue.relation === 'current') ?? null,
    [context],
  )

  const anchorLabel = useMemo(() => {
    if (currentIssue && seriesName) return `${seriesName} #${currentIssue.issue_number}`
    return fallbackAnchorLabel
  }, [currentIssue, seriesName, fallbackAnchorLabel])

  const prerequisiteLanes = useMemo(
    () => buildPrerequisiteLanes(context.local_chain.edges, context.issue_id),
    [context],
  )
  const { fromCurrent, later: rawLater } = classifyEdgesRelativeToCurrent(
    context.local_chain.edges,
    context.issue_id,
  )
  const later = useMemo(() => {
    if (prerequisiteLanes.length === 0) return rawLater
    const prerequisiteIds = new Set(prerequisiteLanes.flatMap((lane) => lane.map((step) => step.issueId)))
    // Prerequisites that are two hops away (e.g. MM6 -> Evil1 -> current) appear in rawLater
    // but must not be rendered as downstream context or they compete with the anchored path.
    return rawLater.filter(
      (edge) =>
        !prerequisiteIds.has(edge.source_issue_id) && !prerequisiteIds.has(edge.target_issue_id),
    )
  }, [prerequisiteLanes, rawLater])

  const blockerLabels = useMemo(() => {
    if (!readinessState.readiness || readinessState.readiness.is_readable) return []
    const labels: string[] = []
    for (const blocker of readinessState.readiness.blockers) {
      for (const detail of blocker.unread_issue_details) {
        if (!labels.includes(detail.label)) labels.push(detail.label)
      }
      if (blocker.unread_issue_details.length === 0 && !labels.includes(blocker.source_label)) {
        labels.push(blocker.source_label)
      }
    }
    return labels
  }, [readinessState])

  const readinessResolved =
    !readinessState.isLoading &&
    !readinessState.error &&
    readinessState.readiness !== null

  return (
    <section
      aria-labelledby="reading-path-heading"
      className="rounded-2xl p-4"
      style={{ border: '1px solid rgba(6,182,212,0.3)', backgroundColor: 'rgba(6, 182, 212, 0.09)' }}
    >
      <h3
        id="reading-path-heading"
        className="font-bold text-[var(--theme-text-primary)]"
        style={readingContextType('sectionHeading')}
      >
        Your Place in the Story
      </h3>

      {readinessResolved && readinessState.readiness?.is_readable && (
        <p
          className="mt-2 flex flex-wrap items-center gap-x-2 font-bold text-emerald-300"
          style={readingContextType('bodyCopy')}
          role="status"
          data-testid="reading-path-readable"
        >
          <span aria-hidden="true">✓</span>
          <span>Caught up — you can read {anchorLabel} now.</span>
        </p>
      )}

      {readinessResolved && readinessState.readiness && !readinessState.readiness.is_readable && (
        <p
          className="mt-2 flex flex-wrap items-center gap-x-2 font-bold text-amber-300"
          style={readingContextType('bodyCopy')}
          role="status"
          data-testid="reading-path-blocked"
        >
          <span aria-hidden="true">✳</span>
          <span>
            Not yet — read {blockerLabels.join(', ') || 'your prerequisites'} before {anchorLabel}.
          </span>
        </p>
      )}

      {prerequisiteLanes.length > 0 && (
        <div className="mt-3 space-y-3" aria-label="Before this issue">
          <div
            className="font-bold uppercase tracking-wider text-[var(--theme-text-muted)]"
            style={readingContextType('statLabel')}
          >
            Before this issue
          </div>
          {prerequisiteLanes.map((lane, laneIndex) => (
            <ol
              key={lane.map((step) => step.issueId).join('-')}
              className="space-y-1"
              aria-label={
                prerequisiteLanes.length > 1
                  ? `Prerequisite path ${laneIndex + 1} of ${prerequisiteLanes.length}`
                  : undefined
              }
            >
              {lane.map((step, stepIndex) => (
                <li key={step.issueId} className="min-w-0 space-y-1">
                  {stepIndex > 0 && (
                    <div className="pl-1 text-[var(--theme-text-muted)]" aria-hidden="true">
                      ↓
                    </div>
                  )}
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                    <span
                      aria-hidden="true"
                      className="flex-shrink-0 font-black"
                      style={{
                        color: step.status === 'read' ? 'rgb(52, 211, 153)' : 'rgba(250, 204, 21, 0.7)',
                      }}
                    >
                      {step.status === 'read' ? '✓' : '○'}
                    </span>
                    <EdgeEndpoint label={step.label} threadId={step.threadId} onOpen={onOpenThread} />
                    <StepStateMark status={step.status} />
                  </div>
                  {step.explanations.map((copy) => (
                    <div
                      key={copy}
                      className="break-words pl-6 italic text-[var(--theme-text-muted)]"
                      style={readingContextType('bodyCopy')}
                    >
                      {copy}
                    </div>
                  ))}
                </li>
              ))}
            </ol>
          ))}
          {prerequisiteLanes.length > 1 && (
            <p className="italic text-[var(--theme-text-muted)]" style={readingContextType('metaLabel')}>
              All of these paths lead into {anchorLabel}.
            </p>
          )}
        </div>
      )}

      <div
        className="mt-4 flex flex-wrap items-center gap-x-2 gap-y-1 rounded-lg px-3 py-2"
        style={{
          borderLeft: '4px solid var(--theme-continuity-accent)',
          backgroundColor: 'rgba(6,182,212,0.14)',
        }}
        data-testid="reading-path-anchor"
        aria-label={`Current issue: ${anchorLabel}`}
      >
        <span aria-hidden="true">📍</span>
        <span
          className="font-mono font-bold text-[var(--theme-text-primary)]"
          style={readingContextType('primaryValue')}
        >
          {anchorLabel}
        </span>
        <span
          className="font-bold uppercase tracking-wider text-[var(--theme-comic-accent)]"
          style={readingContextType('statLabel')}
        >
          You are here
        </span>
      </div>

      {fromCurrent.length > 0 && (
        <div className="mt-3 space-y-2" aria-label="After you read this">
          <div
            className="font-bold uppercase tracking-wider text-[var(--theme-text-muted)]"
            style={readingContextType('statLabel')}
          >
            After you read this
          </div>
          {fromCurrent.map((edge) => (
            <EdgeRow key={`from-${edge.kind}-${edge.id}`} edge={edge} onOpen={onOpenThread} />
          ))}
        </div>
      )}

      {later.length > 0 && (
        <div className="mt-3 space-y-2 opacity-75" aria-label="Later continuity">
          <div
            className="font-bold uppercase tracking-wider text-[var(--theme-text-muted)]"
            style={readingContextType('statLabel')}
          >
            Later continuity
          </div>
          <p className="italic text-[var(--theme-text-muted)]" style={readingContextType('metaLabel')}>
            These unlock after your current read — they don&apos;t block {anchorLabel}.
          </p>
          {later.map((edge) => (
            <EdgeRow key={`later-${edge.kind}-${edge.id}`} edge={edge} onOpen={onOpenThread} subdued />
          ))}
        </div>
      )}

      {prerequisiteLanes.length === 0 && fromCurrent.length === 0 && later.length === 0 && (
        <p className="mt-2 italic text-[var(--theme-text-muted)]" style={readingContextType('bodyCopy')}>
          No continuity prerequisites are recorded around {anchorLabel}.
        </p>
      )}
    </section>
  )
}

function EdgeRow({
  edge,
  onOpen,
  subdued = false,
}: {
  edge: ReaderContextEdge
  onOpen: (threadId: number) => void
  subdued?: boolean
}) {
  const arrow = edge.kind === 'dependency' ? '→' : '↝'
  const accent = subdued ? 'rgba(165,243,252,0.45)' : 'rgb(165,243,252)'
  const copy = edge.explanation ?? edge.note
  return (
    <div
      className={`flex items-start gap-3 rounded-lg px-3 py-2${subdued ? ' opacity-80' : ''}`}
      style={{
        borderLeft: `3px solid ${accent}`,
        backgroundColor: subdued ? 'rgba(255,255,255,0.02)' : 'rgba(165, 243, 252, 0.05)',
      }}
    >
      <div className="mt-1 h-2 w-2 flex-shrink-0 rounded-full" style={{ backgroundColor: accent }}></div>
      <div className="min-w-0 flex-1 space-y-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <EdgeEndpoint label={edge.source_label} threadId={edge.source_thread_id} onOpen={onOpen} />
          <span className="text-[var(--theme-text-muted)]" aria-hidden="true">{arrow}</span>
          <EdgeEndpoint label={edge.target_label} threadId={edge.target_thread_id} onOpen={onOpen} />
        </div>
        {copy ? (
          <div className="break-words italic text-[var(--theme-text-muted)]" style={readingContextType('bodyCopy')}>
            {copy}
          </div>
        ) : null}
      </div>
    </div>
  )
}
