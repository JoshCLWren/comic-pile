import { useState, useEffect, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import type { ReadingOrder } from '../../../services/api-reading-orders'
import type { ConnectedThreadInfo } from '../../../types'
import type { RatingThread } from '../types'
import { useReaderContext } from '../../../hooks/useReaderContext'
import { RATING_THRESHOLD, getDieDirection, getProgressPercentage } from '../utils'
import { ComicPillar } from './ComicPillar'
import { ContinuityReadinessSummary } from './ContinuityReadinessSummary'
import { ReadingOrderGroups } from './ReadingOrderGroups'
import { ReadingRouteExplanation } from './ReadingRouteExplanation'
import ContinuityCorrectionDialog from '../../../components/ContinuityCorrectionDialog'
import { SeriesPanel } from './SeriesPanel'
import { CrossoverAnalytics } from './CrossoverAnalytics'
import Tooltip from '../../../components/Tooltip'

interface RatingViewProps {
  activeRatingThread: RatingThread | null
  currentDie: number
  rolledResult: number | null
  rating: number
  predictedDie: number
  hasValidRolledResult?: boolean
  poolSize?: number
  errorMessage: string
  rateIsPending: boolean
  snoozeIsPending: boolean
  dismissIsPending: boolean
  readingOrders: ReadingOrder[]
  connectedThreads: ConnectedThreadInfo[]
  onUpdateRating: (value: string) => void
  onSubmitRating: (finishSession: boolean) => void
  onSnooze: () => void
  onCancel: () => void
  onRefreshThread: () => void
}

function ratingToStars(rating: number | null): string {
  if (rating === null) return ''
  const fullStars = Math.floor(rating)
  const hasHalf = rating % 1 >= 0.5
  return '★'.repeat(fullStars) + (hasHalf ? '½' : '')
}

export function RatingView({
  activeRatingThread,
  currentDie,
  rolledResult,
  rating,
  predictedDie,
  errorMessage,
  rateIsPending,
  snoozeIsPending,
  dismissIsPending,
  readingOrders,
  connectedThreads,
  onUpdateRating,
  onSubmitRating,
  onSnooze,
  onCancel,
  onRefreshThread,
}: RatingViewProps) {
  const [isContinuityDialogOpen, setIsContinuityDialogOpen] = useState(false)
  const [isRouteExplanationOpen, setIsRouteExplanationOpen] = useState(false)
  const navigate = useNavigate()
  const issueId = activeRatingThread?.issue_id ?? activeRatingThread?.next_issue_id ?? null
  const { context: readerContext } = useReaderContext(issueId)
  const dieDirection = getDieDirection(currentDie, predictedDie)
  const isLastIssue = activeRatingThread?.issues_remaining === 1
  const threadTitle = activeRatingThread?.title ?? 'Loading…'
  const issueNumber = activeRatingThread?.next_issue_number ?? activeRatingThread?.issue_number ?? null
  const progress = getProgressPercentage(activeRatingThread)

  const seriesName = useMemo(() => readerContext?.series.series_name ?? null, [readerContext])
  const currentIssue = useMemo(() => readerContext?.local_chain.issues.find((i) => i.relation === 'current') ?? null, [readerContext])
  const previousIssues = useMemo(() => readerContext?.local_chain.issues.filter((i) => i.relation === 'previous') ?? [], [readerContext])
  const nextIssues = useMemo(() => readerContext?.local_chain.issues.filter((i) => i.relation === 'next' || i.relation === 'future') ?? [], [readerContext])

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
  const upcomingCrossovers = useMemo(() => readerContext?.crossovers.filter((c) => !c.applies_to_current_issue) ?? [], [readerContext])
  const dependencyEdges = useMemo(() => readerContext?.local_chain.edges.filter((e) => e.kind === 'dependency') ?? [], [readerContext])
  const continuityEdges = useMemo(() => readerContext?.local_chain.edges.filter((e) => e.kind === 'continuity') ?? [], [readerContext])

  const openCurrentThread = () => {
    if (activeRatingThread) navigate(`/thread/${activeRatingThread.id}`)
  }
  const openCrossoversPage = () => navigate('/crossovers')
  const openThread = (threadId: number) => navigate(`/thread/${threadId}`)

  // Ensure engine details is collapsed by default (no open attribute)
  const [engineOpen, setEngineOpen] = useState(false)

  // For accessibility: keep details closed initially
  useEffect(() => {
    setEngineOpen(false)
  }, [issueId])

  const hasConnectedContent =
    (readerContext && seriesName) ||
    currentCrossovers.length > 0 ||
    upcomingCrossovers.length > 0 ||
    dependencyEdges.length > 0 ||
    continuityEdges.length > 0 ||
    readingOrders.length > 0 ||
    (readerContext?.crossovers.length ?? 0) > 0

  const hasReadingContextContent = readingOrders.length > 0 || connectedThreads.length > 0
  const gridCols = hasReadingContextContent
    ? 'xl:grid-cols-[minmax(0,26fr)_minmax(0,46fr)_minmax(0,28fr)]'
    : 'xl:grid-cols-[minmax(0,50fr)_minmax(0,50fr)]'

  return (
    <div className="relative z-10 space-y-4 p-3 md:p-4" data-testid="roll-result-hierarchy">
      <div className={`grid gap-4 md:grid-cols-2 md:gap-6 ${gridCols}`} data-testid="rating-pillars-grid">
        <div className="md:row-span-2 xl:row-span-1">
          {/* Tier 1: What am I reading? */}
          <section data-testid="tier-what-am-i-reading" aria-labelledby="tier-what-heading" className="space-y-3">
        <h2 id="tier-what-heading" className="text-sm font-black uppercase tracking-[0.15em] text-stone-200">
          What am I reading?
        </h2>
        <p className="text-[11px] text-stone-500">Series, issue, and your progress in this comic.</p>
        <ComicPillar activeRatingThread={activeRatingThread} onRefreshThread={onRefreshThread} />
        {activeRatingThread && (
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] font-bold text-stone-500">
            {activeRatingThread.total_issues && issueNumber != null ? (
              <span>Issue {issueNumber} of {activeRatingThread.total_issues}</span>
            ) : null}
            {activeRatingThread.total_issues && issueNumber != null ? <span aria-hidden="true">·</span> : null}
            <span>{progress}% complete</span>
            <span aria-hidden="true">·</span>
            <span>{activeRatingThread.issues_remaining} left</span>
          </div>
        )}
      </section>
        </div>

      {/* Tier 2: Why this one / can I read it? */}
      <section data-testid="tier-why-this-one" aria-labelledby="tier-why-heading" className="space-y-3">
        <h2 id="tier-why-heading" className="text-sm font-black uppercase tracking-[0.15em] text-stone-200">
          Why this one / can I read it?
        </h2>
        <p className="text-[11px] text-stone-500">Readiness and blockers for this issue, in human language.</p>
        <ContinuityReadinessSummary issueId={issueId} />
        {readingOrders.length === 0 && connectedThreads.length === 0 && readerContext && (
          <p className="text-[11px] text-stone-400">No blockers reported for this issue. Ready to read.</p>
        )}
        <div className="pt-1">
          <ReadingOrderGroups threadId={activeRatingThread?.id} className="text-[11px] font-mono text-amber-500" />
        </div>
        {readingOrders.length > 0 && (
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setIsRouteExplanationOpen(true)}
              className="min-h-11 rounded-lg px-3 text-[10px] font-black transition focus:ring-2"
              style={{
                border: '1px solid rgba(212,137,14,0.4)',
                backgroundColor: 'rgba(212, 137, 14, 0.09)',
                color: 'rgb(250, 204, 139)',
              }}
              aria-label={`Explain why ${threadTitle} ${issueNumber != null ? `#${issueNumber}` : ''} is next`}
            >
              Explain why this issue
            </button>
          </div>
        )}
      </section>

      {/* Tier 3: What's connected? */}
      <section data-testid="tier-whats-connected" aria-labelledby="tier-connected-heading" className="space-y-3">
        <h2 id="tier-connected-heading" className="text-sm font-black uppercase tracking-[0.15em] text-stone-200">
          What&apos;s connected?
        </h2>
        <p className="text-[11px] text-stone-500">Crossovers and story connections for this issue, with real names.</p>

        {!hasConnectedContent && (
          <p className="text-[11px] text-stone-500 italic">No crossover or connection data for this issue yet.</p>
        )}

        {readerContext && seriesName && (
          <div className="rounded-2xl p-4" style={{ border: '1px solid rgba(6,182,212,0.3)', backgroundColor: 'rgba(6, 182, 212, 0.09)' }}>
            <h3 className="text-[10px] font-black uppercase tracking-[0.18em]" style={{ color: 'var(--theme-continuity-accent)' }}>
              Where you are in {seriesName}
            </h3>
            {allCrossoverMemberships.length > 0 && (
              <div className="flex flex-wrap gap-1 mt-3 mb-3" aria-label="Crossover memberships">
                {allCrossoverMemberships.map((crossover) => (
                  <button
                    key={crossover.id}
                    type="button"
                    className="rounded-full px-2 py-0.5 text-[8px] font-bold transition"
                    style={{
                      border: '1px solid rgba(212,137,14,0.4)',
                      backgroundColor: 'rgba(212, 137, 14, 0.12)',
                      color: 'rgb(250, 204, 139)',
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
                    className={`flex items-center gap-3 ${isCurrent ? 'border-l-2 border-l-solid border-l-[var(--theme-continuity-accent)] pl-3' : 'pl-5'} group cursor-pointer`}
                    role="listitem"
                    tabIndex={0}
                    onClick={openCurrentThread}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault()
                        openCurrentThread()
                      }
                    }}
                    aria-label={`Open ${threadTitle} issue ${issue.issue_number}`}
                  >
                    <div
                      className="flex-shrink-0 w-2 h-2 rounded-full"
                      style={{
                        backgroundColor: isCurrent
                          ? 'var(--theme-continuity-accent)'
                          : isPrevious
                            ? 'rgba(6,182,212,0.3)'
                            : 'rgba(6,182,212,0.1)',
                      }}
                    ></div>
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
                            <span className="text-[9px] font-bold whitespace-nowrap" style={{ color: 'var(--theme-continuity-accent)' }}>
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
          </div>
        )}

        {readerContext && (currentCrossovers.length > 0 || upcomingCrossovers.length > 0) && (
          <div className="rounded-2xl p-4" style={{ border: '1px solid rgba(6,182,212,0.3)', backgroundColor: 'rgba(6, 182, 212, 0.09)' }}>
            <h3 className="text-[10px] font-black uppercase tracking-[0.18em]" style={{ color: 'var(--theme-continuity-accent)' }}>
              Crossovers for this issue
            </h3>
            <p className="text-[9px] text-stone-500 mt-1 mb-3">Being part of a crossover doesn&apos;t block reading by itself.</p>
            {currentCrossovers.length > 0 && (
              <div className="space-y-2 mb-4">
                <div className="font-bold text-[9px] text-stone-500 mb-1">Current issue crossovers</div>
                <div className="flex flex-wrap gap-1">
                  {currentCrossovers.map((crossover) => (
                    <button
                      key={crossover.id}
                      type="button"
                      className="rounded-full px-2 py-1 text-[9px] font-bold transition"
                      style={{
                        border: '1px solid rgba(212,137,14,0.4)',
                        backgroundColor: 'rgba(212, 137, 14, 0.12)',
                        color: 'rgb(250, 204, 139)',
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
                <div className="font-bold text-[9px] text-stone-500 mb-1">Upcoming crossovers</div>
                {upcomingCrossovers.map((crossover) => (
                  <button
                    key={crossover.id}
                    type="button"
                    className="w-full flex items-center gap-3 px-2 py-1 text-left transition"
                    style={{ borderLeft: '3px solid rgb(250, 204, 139)', backgroundColor: 'rgba(250, 204, 139, 0.05)' }}
                    onClick={openCrossoversPage}
                    aria-label={`Open crossover ${crossover.name}`}
                  >
                    <div className="flex-shrink-0 w-2 h-2 rounded-full" style={{ backgroundColor: 'rgb(250, 204, 139)' }}></div>
                    <div className="flex-1 space-y-0.5">
                      <div className="flex items-center justify-between text-[8px]">
                        <span>{crossover.name}</span>
                        {crossover.next_member && <span className="text-stone-400">— starts at #{crossover.next_member.issue_number}</span>}
                      </div>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        {readerContext && (dependencyEdges.length > 0 || continuityEdges.length > 0) && (
          <div className="rounded-2xl p-4" style={{ border: '1px solid rgba(6,182,212,0.3)', backgroundColor: 'rgba(6, 182, 212, 0.09)' }}>
            <h3 className="text-[10px] font-black uppercase tracking-[0.18em]" style={{ color: 'var(--theme-continuity-accent)' }}>
              Story connections
            </h3>
            <div className="space-y-2 mt-3">
              {dependencyEdges.length > 0 && (
                <div className="space-y-1">
                  <div className="font-bold text-[9px] text-stone-500 mb-1">
                    {dependencyEdges.every((e) => e.target_issue_id === (readerContext.issue_id ?? null))
                      ? 'Blocked by:'
                      : dependencyEdges.every((e) => e.source_issue_id === (readerContext.issue_id ?? null))
                        ? 'Blocks:'
                        : 'Connections:'}
                  </div>
                  {dependencyEdges.map((edge) => (
                    <div
                      key={`dependency-${edge.id}`}
                      className="flex items-center gap-3 px-2 py-1"
                      style={{ borderLeft: '3px solid rgb(250, 204, 139)', backgroundColor: 'rgba(250, 204, 139, 0.05)' }}
                    >
                      <div className="flex-shrink-0 w-2 h-2 rounded-full" style={{ backgroundColor: 'rgb(250, 204, 139)' }}></div>
                      <div className="flex-1 space-y-0.5 min-w-0">
                        <div className="flex items-center gap-2 text-[8px] flex-wrap">
                          {edge.source_thread_id !== null ? (
                            <button
                              type="button"
                              className="font-mono truncate underline decoration-dotted underline-offset-2"
                              onClick={() => openThread(edge.source_thread_id!)}
                              aria-label={`Open thread for ${edge.source_label ?? `#${edge.source_issue_id}`}`}
                            >
                              {edge.source_label ?? `#${edge.source_issue_id}`}
                            </button>
                          ) : (
                            <span className="font-mono truncate">{edge.source_label ?? `#${edge.source_issue_id}`}</span>
                          )}
                          <span className="text-stone-400" aria-hidden="true">
                            →
                          </span>
                          {edge.target_thread_id !== null ? (
                            <button
                              type="button"
                              className="font-mono truncate underline decoration-dotted underline-offset-2"
                              onClick={() => openThread(edge.target_thread_id!)}
                              aria-label={`Open thread for ${edge.target_label ?? `#${edge.target_issue_id}`}`}
                            >
                              {edge.target_label ?? `#${edge.target_issue_id}`}
                            </button>
                          ) : (
                            <span className="font-mono truncate">{edge.target_label ?? `#${edge.target_issue_id}`}</span>
                          )}
                        </div>
                        {edge.explanation && <div className="text-[8px] text-stone-400 italic truncate">{edge.explanation}</div>}
                        {edge.note && !edge.explanation && <div className="text-[8px] text-stone-400 italic truncate">{edge.note}</div>}
                      </div>
                    </div>
                  ))}
                </div>
              )}
              {continuityEdges.length > 0 && (
                <div className="space-y-1">
                  <div className="font-bold text-[9px] text-stone-500 mb-1">Continuity:</div>
                  {continuityEdges.map((edge) => (
                    <div
                      key={`continuity-${edge.id}`}
                      className="flex items-center gap-3 px-2 py-1"
                      style={{ borderLeft: '3px solid rgb(165, 243, 252)', backgroundColor: 'rgba(165, 243, 252, 0.05)' }}
                    >
                      <div className="flex-shrink-0 w-2 h-2 rounded-full" style={{ backgroundColor: 'rgb(165, 243, 252)' }}></div>
                      <div className="flex-1 space-y-0.5 min-w-0">
                        <div className="flex items-center gap-2 text-[8px] flex-wrap">
                          {edge.source_thread_id !== null ? (
                            <button
                              type="button"
                              className="font-mono truncate underline decoration-dotted underline-offset-2"
                              onClick={() => openThread(edge.source_thread_id!)}
                              aria-label={`Open thread for ${edge.source_label ?? `#${edge.source_issue_id}`}`}
                            >
                              {edge.source_label ?? `#${edge.source_issue_id}`}
                            </button>
                          ) : (
                            <span className="font-mono truncate">{edge.source_label ?? `#${edge.source_issue_id}`}</span>
                          )}
                          <span className="text-stone-400" aria-hidden="true">
                            ↝
                          </span>
                          {edge.target_thread_id !== null ? (
                            <button
                              type="button"
                              className="font-mono truncate underline decoration-dotted underline-offset-2"
                              onClick={() => openThread(edge.target_thread_id!)}
                              aria-label={`Open thread for ${edge.target_label ?? `#${edge.target_issue_id}`}`}
                            >
                              {edge.target_label ?? `#${edge.target_issue_id}`}
                            </button>
                          ) : (
                            <span className="font-mono truncate">{edge.target_label ?? `#${edge.target_issue_id}`}</span>
                          )}
                        </div>
                        {edge.explanation && <div className="text-[8px] text-stone-400 italic truncate">{edge.explanation}</div>}
                        {edge.note && !edge.explanation && <div className="text-[8px] text-stone-400 italic truncate">{edge.note}</div>}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}

        {readingOrders.length > 0 && (
          <div className="rounded-2xl p-3" style={{ border: '1px solid rgba(255,255,255,0.1)', backgroundColor: 'rgba(255,255,255,0.04)' }}>
            <h3 className="text-[10px] font-black uppercase tracking-[0.18em] text-stone-500">In your reading lists</h3>
            <div className="grid gap-2 md:grid-cols-2 mt-2">
              {readingOrders.map((order) => {
                const routeProgress = order.total_items > 0 ? Math.round((order.completed_items / order.total_items) * 100) : 0
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
                    <p className="mt-1 text-[10px] font-bold text-stone-500">{routeProgress}% complete</p>
                  </article>
                )
              })}
            </div>
          </div>
        )}

        {readerContext && (
          <>
            <SeriesPanel series={readerContext.series} />
            <CrossoverAnalytics crossovers={readerContext.crossovers} />
          </>
        )}
      </section>

      {/* Your rating - visible without opening engine details */}
      <section aria-labelledby="rating-heading" className="space-y-3 rounded-2xl p-3" style={{ border: '1px solid rgba(168,85,247,0.2)', backgroundColor: 'var(--theme-bg-panel)' }}>
        <div className="flex items-end justify-between gap-3">
          <div>
            <Tooltip content={`Ratings of ${RATING_THRESHOLD.toFixed(1)}+ move the thread to the front and step the die down. Lower ratings move it past the next roll range and step the die up.`}>
              <h3 id="rating-heading" className="cursor-help text-[10px] font-black uppercase tracking-[0.18em] text-stone-500">
                Your rating
              </h3>
            </Tooltip>
            <p id="rating-value" className={`mt-1 text-4xl font-black ${rating >= RATING_THRESHOLD ? 'text-amber-500' : 'text-red-600'}`}>
              {rating.toFixed(1)}
            </p>
          </div>
          <div className="text-right">
            <p className="text-sm font-black text-stone-200">d{currentDie} → d{predictedDie}</p>
            <p className="text-[10px] font-bold text-stone-500">{dieDirection}</p>
          </div>
        </div>
        <input
          type="range"
          id="rating-input"
          name="rating"
          min="0.5"
          max="5.0"
          step="0.5"
          value={rating}
          className="h-4 w-full"
          aria-label="Rating from 0.5 to 5.0 in steps of 0.5"
          aria-describedby="rating-value queue-effect"
          onChange={(event) => onUpdateRating(event.target.value)}
        />
        <p id="queue-effect" className="text-[11px] font-bold leading-relaxed text-stone-400">
          {rating >= RATING_THRESHOLD ? 'Moves this thread to the front of the queue.' : 'Moves this thread beyond the next roll range.'}
        </p>
        {isLastIssue && (
          <div className="rounded-xl border border-amber-600/20 bg-amber-600/10 p-3 text-center">
            <p className="text-[10px] font-black uppercase tracking-[0.15em] text-amber-500">This is the last issue in the thread</p>
          </div>
        )}
      </section>

      {/* Tier 4: Engine details - collapsed by default */}
      <details data-testid="tier-engine-details" open={engineOpen} onToggle={(e) => setEngineOpen((e.target as HTMLDetailsElement).open)} className="rounded-2xl p-3" style={{ border: '1px solid rgba(255,255,255,0.12)', backgroundColor: 'rgba(255,255,255,0.03)' }}>
        <summary className="cursor-pointer list-none flex items-center justify-between">
          <h2 id="tier-engine-heading" className="text-sm font-black uppercase tracking-[0.15em] text-stone-300">
            Engine details
          </h2>
          <span className="text-[10px] font-bold text-stone-500">{engineOpen ? 'Hide' : 'Show'}</span>
        </summary>
        <div className="mt-3 space-y-3">
          <p className="text-[11px] text-stone-500">Ladder state, raw graph diagnostics, and correction tooling.</p>
          <div className="grid grid-cols-2 gap-4 text-center pb-3 border-b border-white/10">
            <div>
              {rolledResult !== null && currentDie !== null ? (
                <>
                  <div className="text-[9px] font-bold text-stone-500">Roll Result</div>
                  <div className="text-[11px] font-mono text-amber-500">Rolled {rolledResult} on d{currentDie}</div>
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
              <div className="text-[11px] font-mono text-amber-500">{progress}%</div>
            </div>
          </div>
          <div className="text-[10px] font-mono text-stone-500 space-y-1" data-testid="engine-diagnostics">
            <div>Die: d{currentDie} → d{predictedDie} ({dieDirection})</div>
            {readerContext && <div>Issue ID: {readerContext.issue_id}</div>}
            {readerContext && <div>Local chain: {readerContext.local_chain.issues.length} issues, {readerContext.local_chain.edges.length} edges</div>}
            {dependencyEdges.length > 0 && <div>Dependency edges: {dependencyEdges.map((e) => e.id).join(', ')}</div>}
            {continuityEdges.length > 0 && <div>Continuity edges: {continuityEdges.map((e) => e.id).join(', ')}</div>}
            {allCrossoverMemberships.length > 0 && <div>Memberships: {allCrossoverMemberships.map((m) => m.name).join(', ')}</div>}
          </div>
          {connectedThreads.length > 0 && activeRatingThread && (
            <div>
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
          )}
        </div>
      </details>

      <div
        className={`md:col-span-2 md:row-start-3 xl:col-start-2 xl:row-start-2 ${hasReadingContextContent ? 'xl:col-span-2' : 'xl:col-end-3'}`}
        data-testid="rating-actions-grid-cell"
      >
        <div className="rating-actions sticky bottom-0 -mx-3 space-y-2 border-t border-white/10 bg-white/[0.04] px-3 pt-3 pb-[calc(env(safe-area-inset-bottom)+5.5rem)] backdrop-blur md:static md:-mx-4 md:px-4 md:pb-3" data-testid="rating-actions">
          {errorMessage ? (
            <div id="error-message" className="text-center text-[10px] font-bold text-rose-500" role="alert">
              {errorMessage}
            </div>
          ) : null}
          <button
            type="button"
            onClick={() => onSubmitRating(false)}
            disabled={rateIsPending}
            data-testid="save-and-continue"
            className="w-full rounded-xl border border-amber-600/50 bg-amber-600/25 py-3.5 text-xs font-black uppercase tracking-[0.15em] transition hover:bg-amber-600/35 focus:ring-2 focus:ring-amber-500 disabled:opacity-50 active:scale-[0.98]"
          >
            {rateIsPending ? 'Saving…' : activeRatingThread?.issues_remaining === 1 ? 'Mark read & complete' : 'Mark read & save'}
          </button>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={onSnooze}
              disabled={snoozeIsPending}
              className="min-h-11 flex-1 rounded-xl border border-white/10 bg-white/5 py-3 text-xs font-black uppercase tracking-[0.15em] text-stone-300 transition hover:bg-white/10 focus:ring-2 focus:ring-amber-500 disabled:opacity-50"
            >
              {snoozeIsPending ? 'Snoozing…' : 'Snooze'}
            </button>
            <button
              type="button"
              onClick={onCancel}
              disabled={dismissIsPending}
              className="min-h-11 flex-1 rounded-xl border border-rose-600/30 bg-rose-600/10 py-3 text-xs font-black uppercase tracking-[0.15em] text-rose-400 transition hover:bg-rose-600/20 focus:ring-2 focus:ring-rose-500 disabled:opacity-50"
            >
              Cancel roll
            </button>
          </div>
        </div>
      </div>
      </div>

      <ReadingRouteExplanation
        isOpen={isRouteExplanationOpen}
        issueId={issueId}
        issueLabel={`${threadTitle}${issueNumber != null ? ` #${issueNumber}` : ''}`}
        readingOrders={readingOrders}
        connectedThreads={connectedThreads}
        onClose={() => setIsRouteExplanationOpen(false)}
      />

      {activeRatingThread && (
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
      )}
    </div>
  )
}
