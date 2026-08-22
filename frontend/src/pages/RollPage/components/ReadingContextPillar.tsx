import { useState, useEffect, useMemo } from 'react'
import type { ReadingOrder } from '../../../services/api-reading-orders'
import type { ConnectedThreadInfo } from '../../../types'
import type { RatingThread } from '../types'
import type { ReaderContextResponse } from '../../../types'
import { issuesApi } from '../../../services/api-issues'
import ContinuityCorrectionDialog from '../../../components/ContinuityCorrectionDialog'
import { ContinuityReadinessSummary } from './ContinuityReadinessSummary'
import { ReadingOrderGroups } from './ReadingOrderGroups'
import { ReadingRouteExplanation } from './ReadingRouteExplanation'

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

  return (
    <div className="w-full space-y-4">
      <div className="flex items-center gap-2 border-b-2 pb-2" style={{ borderColor: 'var(--theme-continuity-accent)' }}>
        <span className="text-[10px] font-black uppercase tracking-[0.18em]" style={{ color: 'var(--theme-continuity-accent)' }}>Reading Context</span>
      </div>
      <ContinuityReadinessSummary issueId={issueId} />

      <section className="grid grid-cols-2 gap-4 text-center pb-3 border-b border-[rgba(6,182,212,0.2)]">
        <div>
          {(rolledResult !== null && currentDie !== null) ? (
            <>
              <div className="text-[9px] font-bold text-stone-500">Roll Result</div>
              <div className="text-[11px] font-mono text-amber-500">
                Rolled {rolledResult} on d{currentDie}
              </div>
            </>
          ) : (
            <>
              <div className="text-[9px] font-bold text-stone-500">Roll Result</div>
              <div className="text-[11px] text-stone-400">—</div>
            </>
          )}
        </div>
        
        <div>
          <div className="text-[9px] font-bold text-stone-500">Series Progress</div>
          <ReadingOrderGroups threadId={activeRatingThread?.id} className="text-[11px] font-mono text-amber-500" />
        </div>
      </section>

      {readerContext && seriesName && (
        <section aria-labelledby="local-series-heading" className="rounded-2xl p-4" style={{ border: '1px solid rgba(6,182,212,0.3)', backgroundColor: 'rgba(6, 182, 212, 0.09)' }}>
          <div className="flex items-center justify-between gap-2 mb-3">
            <h3 id="local-series-heading" className="text-[10px] font-black uppercase tracking-[0.18em]" style={{ color: 'var(--theme-continuity-accent)' }}>
              Where you are in {seriesName}
            </h3>
          </div>

          {allCrossoverMemberships.length > 0 && (
            <div className="flex flex-wrap gap-1 mb-3" aria-label="Crossover memberships">
              {allCrossoverMemberships.map((crossover) => (
                <span key={crossover.id} className="rounded-full px-2 py-0.5 text-[8px] font-bold" style={{
                  border: '1px solid rgba(212,137,14,0.4)',
                  backgroundColor: 'rgba(212, 137, 14, 0.12)',
                  color: 'rgb(250, 204, 139)',
                }}>
                  {crossover.name}
                </span>
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
                  className={`flex items-center gap-3 ${isCurrent ? 'border-l-2 border-l-solid border-l-[var(--theme-continuity-accent)] pl-3' : 'pl-5'} group cursor-pointer`}
                  role="listitem"
                  tabIndex={0}
                  onClick={() => undefined}
                  onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); }}}
                >
                  <div className="flex-shrink-0 w-2 h-2 rounded-full" style={{
                    backgroundColor: isCurrent ? 'var(--theme-continuity-accent)' :
                                isPrevious ? 'rgba(6,182,212,0.3)' :
                                'rgba(6,182,212,0.1)'
                  }}></div>
                  
                  <div className="flex-1 space-y-1 min-w-0">
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex-1 min-w-0 flex items-center gap-2">
                        <span className="font-mono text-[10px] truncate">{issue.issue_number}</span>
                        {isPrevious && issue.rating !== null && (
                          <span className="text-[9px] text-amber-500 whitespace-nowrap" aria-label={`Your rating: ${issue.rating} stars`}>
                            {ratingToStars(issue.rating)}
                          </span>
                        )}
                        {isCurrent && (
                          <span className="text-[9px] font-bold text-stone-500 whitespace-nowrap" style={{ color: 'var(--theme-continuity-accent)' }}>
                            You are here
                          </span>
                        )}
                      </div>
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
          <h3 id="reader-context-unavailable-heading" className="text-[10px] font-black uppercase tracking-[0.18em] text-stone-500">
            Local reading context unavailable
          </h3>
          <p className="mt-1 text-[11px] text-stone-400">
            {readerContextError}
          </p>
        </section>
      ) : null}

      {readerContext && (currentCrossovers.length > 0 || upcomingCrossovers.length > 0) && (
        <section aria-labelledby="exact-crossover-heading" className="rounded-2xl p-4" style={{ border: '1px solid rgba(6,182,212,0.3)', backgroundColor: 'rgba(6, 182, 212, 0.09)' }}>
          <div className="flex items-center justify-between gap-2 mb-3">
            <h3 id="exact-crossover-heading" className="text-[10px] font-black uppercase tracking-[0.18em]" style={{ color: 'var(--theme-continuity-accent)' }}>
              Exact Crossover Context
            </h3>
          </div>

          <p className="text-[9px] text-stone-500 mb-3">
            Being part of a crossover doesn't block reading by itself.
          </p>

          {currentCrossovers.length > 0 && (
            <div className="space-y-2 mb-4">
              <div className="font-bold text-[9px] text-stone-500 mb-1">Current Issue Crossovers</div>
              <div className="flex flex-wrap gap-1">
                {currentCrossovers.map((crossover) => (
                  <button
                    key={crossover.id}
                    className="rounded-full px-2 py-1 text-[9px] font-bold transition"
                    style={{
                      border: '1px solid rgba(212,137,14,0.4)',
                      backgroundColor: 'rgba(212, 137, 14, 0.12)',
                      color: 'rgb(250, 204, 139)',
                    }}
                    onClick={() => undefined}
                  >
                    {crossover.name}
                  </button>
                ))}
              </div>
            </div>
          )}

          {upcomingCrossovers.length > 0 && (
            <div className="space-y-2">
              <div className="font-bold text-[9px] text-stone-500 mb-1">Upcoming Crossovers</div>
              {upcomingCrossovers.map((crossover) => (
                <button
                  key={crossover.id}
                  className="w-full flex items-center gap-3 px-2 py-1 text-left transition"
                  style={{ borderLeft: '3px solid rgb(250, 204, 139)', backgroundColor: 'rgba(250, 204, 139, 0.05)' }}
                  onClick={() => undefined}
                >
                  <div className="flex-shrink-0 w-2 h-2 rounded-full" style={{ backgroundColor: 'rgb(250, 204, 139)' }}></div>
                  <div className="flex-1 space-y-0.5">
                    <div className="flex items-center justify-between text-[8px]">
                      <span>{crossover.name}</span>
                      {crossover.next_member && (
                        <span className="text-stone-400">— starts at #{crossover.next_member.issue_number}</span>
                      )}
                    </div>
                  </div>
                </button>
              ))}
            </div>
          )}
        </section>
      )}

      {readerContext && (dependencyEdges.length > 0 || continuityEdges.length > 0) && (
        <section aria-labelledby="dependency-edges-heading" className="rounded-2xl p-4" style={{ border: '1px solid rgba(6,182,212,0.3)', backgroundColor: 'rgba(6, 182, 212, 0.09)' }}>
          <div className="flex items-center justify-between gap-2 mb-3">
            <h3 id="dependency-edges-heading" className="text-[10px] font-black uppercase tracking-[0.18em]" style={{ color: 'var(--theme-continuity-accent)' }}>
              Dependency & Continuity Edges
            </h3>
          </div>

          {(dependencyEdges.length > 0 || continuityEdges.length > 0) ? (
            <div className="space-y-2">
              {dependencyEdges.length > 0 && (
                <div className="space-y-1">
                  <div className="font-bold text-[9px] text-stone-500 mb-1">
                    {dependencyEdges.length === 1 ? 'Blocks:' : 'Blocked by:'}
                  </div>
                  {dependencyEdges.map((edge) => (
                    <div
                      key={`${edge.source_issue_id}-${edge.target_issue_id}`}
                      className="flex items-center gap-3 px-2 py-1 group cursor-pointer"
                      style={{
                        borderLeft: '3px solid rgb(250, 204, 139)',
                        backgroundColor: 'rgba(250, 204, 139, 0.05)'
                      }}
                      onClick={() => undefined}
                    >
                      <div className="flex-shrink-0 w-2 h-2 rounded-full" style={{ backgroundColor: 'rgb(250, 204, 139)' }}></div>
                      <div className="flex-1 space-y-0.5 min-w-0">
                        <div className="flex items-center gap-2 text-[8px] flex-wrap">
                          <span className="font-mono truncate">{edge.source_label ?? `#${edge.source_issue_id}`}</span>
                          <span className="text-stone-400">→</span>
                          <span className="font-mono truncate">{edge.target_label ?? `#${edge.target_issue_id}`}</span>
                        </div>
                        {edge.explanation && (
                          <div className="text-[8px] text-stone-400 italic truncate">
                            {edge.explanation}
                          </div>
                        )}
                        {edge.note && !edge.explanation && (
                          <div className="text-[8px] text-stone-400 italic truncate">
                            {edge.note}
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {continuityEdges.length > 0 && (
                <div className="space-y-1">
                  <div className="font-bold text-[9px] text-stone-500 mb-1">
                    {continuityEdges.length === 1 ? 'Continuity:' : 'Continuity edges:'}
                  </div>
                  {continuityEdges.map((edge) => (
                    <div
                      key={`${edge.source_issue_id}-${edge.target_issue_id}`}
                      className="flex items-center gap-3 px-2 py-1 group cursor-pointer"
                      style={{
                        borderLeft: '3px solid rgb(165, 243, 252)',
                        backgroundColor: 'rgba(165, 243, 252, 0.05)'
                      }}
                      onClick={() => undefined}
                    >
                      <div className="flex-shrink-0 w-2 h-2 rounded-full" style={{ backgroundColor: 'rgb(165, 243, 252)' }}></div>
                      <div className="flex-1 space-y-0.5 min-w-0">
                        <div className="flex items-center gap-2 text-[8px] flex-wrap">
                          <span className="font-mono truncate">{edge.source_label ?? `#${edge.source_issue_id}`}</span>
                          <span className="text-stone-400">↝</span>
                          <span className="font-mono truncate">{edge.target_label ?? `#${edge.target_issue_id}`}</span>
                        </div>
                        {edge.explanation && (
                          <div className="text-[8px] text-stone-400 italic truncate">
                            {edge.explanation}
                          </div>
                        )}
                        {edge.note && !edge.explanation && (
                          <div className="text-[8px] text-stone-400 italic truncate">
                            {edge.note}
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <p className="text-[9px] text-stone-500 text-center py-4">
              No dependency or continuity edges in local neighborhood
            </p>
          )}
        </section>
      )}

      {readingOrders.length > 0 ? (
        <section aria-labelledby="routes-heading" className="space-y-2">
          <div className="flex items-center justify-between gap-2">
            <h3 id="routes-heading" className="text-[10px] font-black uppercase tracking-[0.18em] text-stone-500">
              Reading Routes
            </h3>
            <span className="text-[10px] font-bold text-stone-600">
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
                    <h4 className="truncate text-xs font-black text-stone-200">{order.name}</h4>
                    <span className="shrink-0 text-[10px] font-bold text-stone-500">
                      {order.completed_items}/{order.total_items}
                    </span>
                  </div>
                  <div className="mt-2 h-1.5 overflow-hidden rounded-full" style={{ backgroundColor: 'rgba(255,255,255,0.1)' }} aria-hidden="true">
                    <div className="h-full rounded-full" style={{ backgroundColor: 'var(--theme-primary-action)', width: `${routeProgress}%` }} />
                  </div>
                  <div className="mt-2 flex items-center justify-between gap-2">
                    <p className="text-[10px] font-bold text-stone-500">{routeProgress}% complete</p>
                    <button
                      type="button"
                      onClick={() => setIsRouteExplanationOpen(true)}
                      className="min-h-11 rounded-lg px-3 text-[10px] font-black transition focus:ring-2"
                      style={{
                        border: '1px solid rgba(212,137,14,0.4)',
                        backgroundColor: 'rgba(212, 137, 14, 0.09)',
                        color: 'rgb(250, 204, 139)',
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
            <h3 id="correction-heading" className="text-[10px] font-black uppercase tracking-[0.18em] text-stone-500">
              Continuity Correction
            </h3>
            <button
              type="button"
              onClick={() => setIsContinuityDialogOpen(true)}
              className="min-h-11 rounded-lg px-3 text-[10px] font-black transition"
              style={{
                border: '1px solid rgba(6,182,212,0.4)',
                backgroundColor: 'rgba(6, 182, 212, 0.09)',
                color: 'var(--theme-continuity-accent)',
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
