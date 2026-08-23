import { useState, useEffect, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import type { ReadingOrder } from '../../../services/api-reading-orders'
import type { ConnectedThreadInfo } from '../../../types'
import type { RatingThread } from '../types'
import type { ReaderContextEdge, ReaderContextResponse } from '../../../types'
import { issuesApi } from '../../../services/api-issues'
import ContinuityCorrectionDialog from '../../../components/ContinuityCorrectionDialog'
import { ContinuityReadinessSummary } from './ContinuityReadinessSummary'
import { ReadingOrderGroups } from './ReadingOrderGroups'
import { ReadingRouteExplanation } from './ReadingRouteExplanation'
import { readingContextType } from '../readingContextTypography'

interface ReadingContextPillarProps {
  activeRatingThread: RatingThread | null
  readingOrders: ReadingOrder[]
  connectedThreads: ConnectedThreadInfo[]
  onRefreshThread: () => void
  rolledResult: number | null
  currentDie: number
}

function ratingToStars(rating: number | null): string {
  if (rating === null) return ''
  const fullStars = Math.floor(rating)
  const hasHalf = rating % 1 >= 0.5
  return '★'.repeat(fullStars) + (hasHalf ? '½' : '')
}

function getSeriesNameFromContext(context: ReaderContextResponse): string | null {
  return context.series.series_name ?? null
}

function EdgeEndpoint({
  label,
  fallbackLabel,
  threadId,
  onOpen,
}: {
  label: string | null
  fallbackLabel: string
  threadId: number | null
  onOpen: (threadId: number) => void
}) {
  const endpointStyle = readingContextType('primaryValue')
  if (threadId === null) {
    return (
      <span className="min-w-0 break-words font-mono text-[var(--theme-text-primary)]" style={endpointStyle}>
        {label ?? fallbackLabel}
      </span>
    )
  }
  return (
    <button
      type="button"
      className="min-w-0 break-words text-left font-mono underline decoration-dotted underline-offset-2 text-[var(--theme-text-primary)]"
      style={endpointStyle}
      onClick={() => onOpen(threadId)}
      aria-label={`Open thread for ${label ?? fallbackLabel}`}
    >
      {label ?? fallbackLabel}
    </button>
  )
}

export function ReadingContextPillar({
  activeRatingThread,
  readingOrders,
  connectedThreads,
  onRefreshThread,
  rolledResult,
  currentDie,
}: ReadingContextPillarProps) {
  const [isContinuityDialogOpen, setIsContinuityDialogOpen] = useState(false)
  const [isRouteExplanationOpen, setIsRouteExplanationOpen] = useState(false)
  const navigate = useNavigate()
  const [readerContext, setReaderContext] = useState<ReaderContextResponse | null>(null)
  const [readerContextError, setReaderContextError] = useState<string | null>(null)
  const threadTitle = activeRatingThread?.title ?? 'Loading…'
  const issueNumber = activeRatingThread?.next_issue_number ?? activeRatingThread?.issue_number ?? null
  const issueId = activeRatingThread?.issue_id ?? activeRatingThread?.next_issue_id

  useEffect(() => {
    if (!activeRatingThread || !issueId) {
      setReaderContext(null)
      setReaderContextError(null)
      return
    }

    const abortController = new AbortController()
    let isCurrent = true
    const fetchReaderContext = async () => {
      setReaderContextError(null)
      try {
        const response = await issuesApi.getReaderContext(issueId, { signal: abortController.signal })
        if (isCurrent && !abortController.signal.aborted) {
          setReaderContext(response)
        }
      } catch (error) {
        if (isCurrent && !abortController.signal.aborted) {
          console.error('Failed to fetch reader-context:', error)
          setReaderContextError('Failed to load reading context')
        }
      }
    }

    fetchReaderContext()

    return () => {
      isCurrent = false
      abortController.abort()
    }
  }, [activeRatingThread, issueId])

  const seriesName = useMemo(() => readerContext ? getSeriesNameFromContext(readerContext) : null, [readerContext])

  const currentIssue = useMemo(() => readerContext?.local_chain.issues.find(i => i.relation === 'current') ?? null, [readerContext])
  const previousIssues = useMemo(() => readerContext?.local_chain.issues.filter(i => i.relation === 'previous') ?? [], [readerContext])
  const nextIssues = useMemo(() => readerContext?.local_chain.issues.filter(i => i.relation === 'next' || i.relation === 'future') ?? [], [readerContext])

  const allCrossoverMemberships = useMemo(() => {
    if (!readerContext) return []
    const seen = new Set<number>()
    const memberships: { id: number; name: string }[] = []
    for (const issue of readerContext.local_chain.issues) {
      for (const m of issue.crossover_memberships) {
        if (!seen.has(m.id)) {
          seen.add(m.id)
          memberships.push(m)
        }
      }
    }
    return memberships
  }, [readerContext])

  const currentCrossovers = useMemo(() => currentIssue?.crossover_memberships ?? [], [currentIssue])
  const upcomingCrossovers = useMemo(() => readerContext?.crossovers.filter(c => !c.applies_to_current_issue) ?? [], [readerContext])

  const dependencyEdges = useMemo(() => readerContext?.local_chain.edges.filter(e => e.kind === 'dependency') ?? [], [readerContext])
  const continuityEdges = useMemo(() => readerContext?.local_chain.edges.filter(e => e.kind === 'continuity') ?? [], [readerContext])

  const currentIssueId = readerContext?.issue_id ?? null
  const dependencyHeading = useMemo(() => {
    if (dependencyEdges.length === 0) return null
    if (dependencyEdges.every(e => e.target_issue_id === currentIssueId)) return 'Blocked by:'
    if (dependencyEdges.every(e => e.source_issue_id === currentIssueId)) return 'Blocks:'
    return 'Dependency edges:'
  }, [dependencyEdges, currentIssueId])

  const openCurrentThread = () => {
    if (activeRatingThread) navigate(`/thread/${activeRatingThread.id}`)
  }
  const openCrossoversPage = () => navigate('/crossovers')
  const openThread = (threadId: number) => navigate(`/thread/${threadId}`)

  const renderEdgeExplanation = (edge: { explanation: string | null; note: string | null }) => {
    const copy = edge.explanation ?? (edge.note ? edge.note : null)
    if (!copy) return null
    return (
      <div
        className="break-words italic text-[var(--theme-text-muted)]"
        style={readingContextType('bodyCopy')}
      >
        {copy}
      </div>
    )
  }

  return (
    <div className="w-full space-y-4">
      <div className="flex items-center justify-between gap-2 border-b-2 pb-2" style={{ borderColor: 'var(--theme-continuity-accent)' }}>
        <span
          className="font-black uppercase tracking-[0.14em] text-[var(--theme-text-muted)]"
          style={readingContextType('panelLabel')}
        >
          Reading Context
        </span>
      </div>
      <ContinuityReadinessSummary issueId={issueId} />

      <section className="grid grid-cols-2 gap-x-6 gap-y-3 border-b border-[var(--theme-border)] pb-3">
        <div className="min-w-0">
          <div
            className="font-bold uppercase tracking-wider text-[var(--theme-text-muted)]"
            style={readingContextType('statLabel')}
          >
            Roll Result
          </div>
          <div
            className="mt-1 font-mono font-bold text-[var(--theme-comic-accent)]"
            style={readingContextType('statValue')}
          >
            {(rolledResult !== null && currentDie !== null) ? `Rolled ${rolledResult} on d${currentDie}` : '—'}
          </div>
        </div>

        <div className="min-w-0">
          <div
            className="font-bold uppercase tracking-wider text-[var(--theme-text-muted)]"
            style={readingContextType('statLabel')}
          >
            Series Progress
          </div>
          <ReadingOrderGroups
            threadId={activeRatingThread?.id}
            className="mt-1 font-mono font-bold text-[var(--theme-comic-accent)]"
          />
        </div>
      </section>

      {readerContext && seriesName && (
        <section aria-labelledby="local-series-heading" className="rounded-2xl p-4" style={{ border: '1px solid rgba(6,182,212,0.3)', backgroundColor: 'rgba(6, 182, 212, 0.09)' }}>
          <div className="mb-3 flex items-center justify-between gap-2">
            <h3
              id="local-series-heading"
              className="font-bold text-[var(--theme-text-primary)]"
              style={readingContextType('sectionHeading')}
            >
              Where you are in {seriesName}
            </h3>
          </div>

          {allCrossoverMemberships.length > 0 && (
            <div className="mb-3 flex flex-wrap gap-2" aria-label="Crossover memberships">
              {allCrossoverMemberships.map((crossover) => (
                <button
                  key={crossover.id}
                  type="button"
                  className="rounded-full px-3 py-1 font-bold text-[var(--theme-comic-accent)] transition hover:brightness-125"
                  style={{
                    ...readingContextType('chipLabel'),
                    border: '1px solid rgba(212,137,14,0.4)',
                    backgroundColor: 'rgba(212, 137, 14, 0.12)',
                  }}
                  onClick={openCrossoversPage}
                  aria-label={`Open ${crossover.name} crossover`}
                >
                  {crossover.name}
                </button>
              ))}
            </div>
          )}

          <div className="space-y-2" role="list" aria-label="Series issues">
            {[...previousIssues, ...(currentIssue ? [currentIssue] : []), ...nextIssues].map((issue) => {
              const isCurrent = issue.relation === 'current'
              const isPrevious = issue.relation === 'previous'
              return (
                <div
                  key={issue.issue_id}
                  className={`group flex cursor-pointer items-center gap-3 ${isCurrent ? 'border-l-2 border-l-solid border-l-[var(--theme-continuity-accent)] pl-3' : 'pl-5'}`}
                  role="listitem"
                  tabIndex={0}
                  onClick={openCurrentThread}
                  onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openCurrentThread(); } }}
                  aria-label={`Open ${threadTitle} issue ${issue.issue_number}`}
                >
                  <div className="h-2.5 w-2.5 flex-shrink-0 rounded-full" style={{
                    backgroundColor: isCurrent ? 'var(--theme-continuity-accent)' :
                                isPrevious ? 'rgba(6,182,212,0.3)' :
                                'rgba(6,182,212,0.1)'
                  }}></div>

                  <div className="min-w-0 flex-1">
                    <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
                      <span
                        className="min-w-0 break-words font-mono text-[var(--theme-text-primary)]"
                        style={readingContextType('primaryValue')}
                      >
                        {issue.issue_number}
                      </span>
                      {isPrevious && issue.rating !== null && (
                        <span
                          className="whitespace-nowrap text-[var(--theme-comic-accent)]"
                          style={readingContextType('metaLabel')}
                          aria-label={`Your rating: ${issue.rating} stars`}
                        >
                          {ratingToStars(issue.rating)}
                        </span>
                      )}
                      {isCurrent && (
                        <span
                          className="whitespace-nowrap font-bold uppercase tracking-wider text-[var(--theme-comic-accent)]"
                          style={readingContextType('statLabel')}
                        >
                          You are here
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        </section>
      )}

      {readerContextError && !readerContext ? (
        <section aria-labelledby="reader-context-unavailable-heading" className="rounded-2xl p-3" style={{ border: '1px solid rgba(6,182,212,0.3)', backgroundColor: 'rgba(6, 182, 212, 0.09)' }}>
          <h3
            id="reader-context-unavailable-heading"
            className="font-bold text-rose-300"
            style={readingContextType('sectionHeading')}
          >
            Local reading context unavailable
          </h3>
          <p className="mt-1 text-stone-400" style={readingContextType('bodyCopy')}>
            {readerContextError}
          </p>
        </section>
      ) : null}

      {readerContext && (currentCrossovers.length > 0 || upcomingCrossovers.length > 0) && (
        <section aria-labelledby="exact-crossover-heading" className="rounded-2xl p-4" style={{ border: '1px solid rgba(6,182,212,0.3)', backgroundColor: 'rgba(6, 182, 212, 0.09)' }}>
          <div className="mb-3 flex items-center justify-between gap-2">
            <h3
              id="exact-crossover-heading"
              className="font-bold text-[var(--theme-text-primary)]"
              style={readingContextType('sectionHeading')}
            >
              Exact Crossover Context
            </h3>
          </div>

          <p className="mb-3 text-[var(--theme-text-muted)]" style={readingContextType('bodyCopy')}>
            Being part of a crossover doesn&apos;t block reading by itself.
          </p>

          {currentCrossovers.length > 0 && (
            <div className="mb-4 space-y-2">
              <div
                className="mb-1 font-bold uppercase tracking-wider text-[var(--theme-text-muted)]"
                style={readingContextType('statLabel')}
              >
                Current Issue Crossovers
              </div>
              <div className="flex flex-wrap gap-2">
                {currentCrossovers.map((crossover) => (
                  <button
                    key={crossover.id}
                    type="button"
                    className="rounded-full px-3 py-1 font-bold text-[var(--theme-comic-accent)] transition hover:brightness-125"
                    style={{
                      ...readingContextType('chipLabel'),
                      border: '1px solid rgba(212,137,14,0.4)',
                      backgroundColor: 'rgba(212, 137, 14, 0.12)',
                    }}
                    onClick={openCrossoversPage}
                    aria-label={`Open crossover ${crossover.name}`}
                  >
                    {crossover.name}
                  </button>
                ))}
              </div>
            </div>
          )}

          {upcomingCrossovers.length > 0 && (
            <div className="space-y-2">
              <div
                className="mb-1 font-bold uppercase tracking-wider text-[var(--theme-text-muted)]"
                style={readingContextType('statLabel')}
              >
                Upcoming Crossovers
              </div>
              {upcomingCrossovers.map((crossover) => (
                <button
                  key={crossover.id}
                  type="button"
                  className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left transition hover:bg-white/5"
                  style={{ borderLeft: '3px solid rgb(250, 204, 139)', backgroundColor: 'rgba(250, 204, 139, 0.05)' }}
                  onClick={openCrossoversPage}
                  aria-label={`Open crossover ${crossover.name}`}
                >
                  <div className="h-2.5 w-2.5 flex-shrink-0 rounded-full" style={{ backgroundColor: 'rgb(250, 204, 139)' }}></div>
                  <div className="flex min-w-0 flex-1 flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
                    <span
                      className="min-w-0 break-words font-bold text-[var(--theme-text-primary)]"
                      style={readingContextType('primaryValue')}
                    >
                      {crossover.name}
                    </span>
                    {crossover.next_member && (
                      <span
                        className="whitespace-nowrap text-[var(--theme-text-muted)]"
                        style={readingContextType('metaLabel')}
                      >
                        — starts at #{crossover.next_member.issue_number}
                      </span>
                    )}
                  </div>
                </button>
              ))}
            </div>
          )}
        </section>
      )}

      {readerContext && (dependencyEdges.length > 0 || continuityEdges.length > 0) && (
        <section aria-labelledby="dependency-edges-heading" className="rounded-2xl p-4" style={{ border: '1px solid rgba(6,182,212,0.3)', backgroundColor: 'rgba(6, 182, 212, 0.09)' }}>
          <div className="mb-3 flex items-center justify-between gap-2">
            <h3
              id="dependency-edges-heading"
              className="font-bold text-[var(--theme-text-primary)]"
              style={readingContextType('sectionHeading')}
            >
              Dependency &amp; Continuity Edges
            </h3>
          </div>

          <div className="space-y-3">
            {dependencyEdges.length > 0 && (
              <div className="space-y-2">
                <div
                  className="font-bold uppercase tracking-wider text-[var(--theme-text-muted)]"
                  style={readingContextType('statLabel')}
                >
                  {dependencyHeading}
                </div>
                {dependencyEdges.map((edge) => (
                  <div
                    key={`dependency-${edge.id}`}
                    className="flex items-start gap-3 rounded-lg px-3 py-2"
                    style={{
                      borderLeft: '3px solid rgb(250, 204, 139)',
                      backgroundColor: 'rgba(250, 204, 139, 0.05)'
                    }}
                  >
                    <div className="mt-1 h-2.5 w-2.5 flex-shrink-0 rounded-full" style={{ backgroundColor: 'rgb(250, 204, 139)' }}></div>
                    <div className="min-w-0 flex-1 space-y-1">
                      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                        <EdgeEndpoint
                          label={edge.source_label}
                          fallbackLabel={`#${edge.source_issue_id}`}
                          threadId={edge.source_thread_id}
                          onOpen={openThread}
                        />
                        <span className="text-[var(--theme-text-muted)]" aria-hidden="true">→</span>
                        <EdgeEndpoint
                          label={edge.target_label}
                          fallbackLabel={`#${edge.target_issue_id}`}
                          threadId={edge.target_thread_id}
                          onOpen={openThread}
                        />
                      </div>
                      {renderEdgeExplanation(edge)}
                    </div>
                  </div>
                ))}
              </div>
            )}

            {continuityEdges.length > 0 && (
              <div className="space-y-2">
                <div
                  className="font-bold uppercase tracking-wider text-[var(--theme-text-muted)]"
                  style={readingContextType('statLabel')}
                >
                  {continuityEdges.length === 1 ? 'Continuity:' : 'Continuity edges:'}
                </div>
                {continuityEdges.map((edge) => (
                  <div
                    key={`continuity-${edge.id}`}
                    className="flex items-start gap-3 rounded-lg px-3 py-2"
                    style={{
                      borderLeft: '3px solid rgb(165, 243, 252)',
                      backgroundColor: 'rgba(165, 243, 252, 0.05)'
                    }}
                  >
                    <div className="mt-1 h-2.5 w-2.5 flex-shrink-0 rounded-full" style={{ backgroundColor: 'rgb(165, 243, 252)' }}></div>
                    <div className="min-w-0 flex-1 space-y-1">
                      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                        <EdgeEndpoint
                          label={edge.source_label}
                          fallbackLabel={`#${edge.source_issue_id}`}
                          threadId={edge.source_thread_id}
                          onOpen={openThread}
                        />
                        <span className="text-[var(--theme-text-muted)]" aria-hidden="true">↝</span>
                        <EdgeEndpoint
                          label={edge.target_label}
                          fallbackLabel={`#${edge.target_issue_id}`}
                          threadId={edge.target_thread_id}
                          onOpen={openThread}
                        />
                      </div>
                      {renderEdgeExplanation(edge)}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </section>
      )}

      {readingOrders.length > 0 ? (
        <section aria-labelledby="routes-heading" className="space-y-2">
          <div className="flex items-center justify-between gap-2">
            <h3
              id="routes-heading"
              className="font-bold uppercase tracking-wider text-[var(--theme-text-muted)]"
              style={readingContextType('statLabel')}
            >
              Reading Routes
            </h3>
            <span className="font-bold text-[var(--theme-text-muted)]" style={readingContextType('metaLabel')}>
              {readingOrders.length} active
            </span>
          </div>
          <div className="grid gap-2 md:grid-cols-2">
            {readingOrders.map((order) => {
              const routeProgress = order.total_items > 0
                ? Math.round((order.completed_items / order.total_items) * 100)
                : 0
              return (
                <article key={order.id} className="rounded-xl p-3" style={{ border: '1px solid rgba(255,255,255,0.1)', backgroundColor: 'rgba(255,255,255,0.04)' }}>
                  <div className="flex items-center justify-between gap-3">
                    <h4
                      className="min-w-0 break-words font-black text-stone-200"
                      style={readingContextType('primaryValue')}
                    >
                      {order.name}
                    </h4>
                    <span className="shrink-0 font-bold text-stone-400" style={readingContextType('metaLabel')}>
                      {order.completed_items}/{order.total_items}
                    </span>
                  </div>
                  <div className="mt-2 h-1.5 overflow-hidden rounded-full" style={{ backgroundColor: 'rgba(255,255,255,0.1)' }} aria-hidden="true">
                    <div className="h-full rounded-full" style={{ backgroundColor: 'var(--theme-primary-action)', width: `${routeProgress}%` }} />
                  </div>
                  <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
                    <p className="font-bold text-stone-400" style={readingContextType('metaLabel')}>{routeProgress}% complete</p>
                    <button
                      type="button"
                      onClick={() => setIsRouteExplanationOpen(true)}
                      className="min-h-11 rounded-lg px-3 font-black text-[var(--theme-comic-accent)] transition focus:ring-2 hover:brightness-125"
                      style={{
                        ...readingContextType('actionLabel'),
                        border: '1px solid rgba(212,137,14,0.4)',
                        backgroundColor: 'rgba(212, 137, 14, 0.09)',
                      }}
                      aria-label={`Explain why ${threadTitle} ${issueNumber != null ? `#${issueNumber}` : ''} is next in ${order.name}`}
                    >
                      Explain route
                    </button>
                  </div>
                </article>
              )
            })}
          </div>
        </section>
      ) : null}

      {connectedThreads.length > 0 && activeRatingThread ? (
        <section aria-labelledby="correction-heading" className="space-y-2">
          <div className="flex items-center justify-between gap-2">
            <h3
              id="correction-heading"
              className="font-bold uppercase tracking-wider text-[var(--theme-text-muted)]"
              style={readingContextType('statLabel')}
            >
              Continuity Correction
            </h3>
            <button
              type="button"
              onClick={() => setIsContinuityDialogOpen(true)}
              className="min-h-11 rounded-lg px-3 font-black text-[var(--theme-text-primary)] transition hover:brightness-125"
              style={{
                ...readingContextType('actionLabel'),
                border: '1px solid rgba(6,182,212,0.4)',
                backgroundColor: 'rgba(6, 182, 212, 0.09)',
              }}
            >
              Correct continuity
            </button>
          </div>
        </section>
      ) : null}

      <ReadingRouteExplanation
        isOpen={isRouteExplanationOpen}
        issueId={issueId}
        issueLabel={`${threadTitle}${issueNumber != null ? ` #${issueNumber}` : ''}`}
        readingOrders={readingOrders}
        connectedThreads={connectedThreads}
        onClose={() => setIsRouteExplanationOpen(false)}
      />

      {activeRatingThread ? (
        <ContinuityCorrectionDialog
          isOpen={isContinuityDialogOpen}
          threadId={activeRatingThread.id}
          issueId={issueId}
          issueNumber={issueNumber}
          threadTitle={activeRatingThread.title}
          connectedThreads={connectedThreads}
          onClose={() => setIsContinuityDialogOpen(false)}
          onSuccess={() => {
            setIsContinuityDialogOpen(false)
            onRefreshThread()
          }}
        />
      ) : null}
    </div>
  )
}
