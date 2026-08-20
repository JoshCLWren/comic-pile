import { useState, useEffect } from 'react'
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

export function ReadingContextPillar({
  activeRatingThread,
  readingOrders,
  connectedThreads,
  onRefreshThread,
}: ReadingContextPillarProps) {
  const [isContinuityDialogOpen, setIsContinuityDialogOpen] = useState(false)
  const [isRouteExplanationOpen, setIsRouteExplanationOpen] = useState(false)
  const [readerContext, setReaderContext] = useState<ReaderContextResponse | null>(null)
  const [readerContextError, setReaderContextError] = useState<string | null>(null)
  const [isLoadingReaderContext, setIsLoadingReaderContext] = useState(false)
  const threadTitle = activeRatingThread?.title ?? 'Loading…'
  const issueNumber = activeRatingThread?.next_issue_number ?? activeRatingThread?.issue_number ?? null
  const issueId = activeRatingThread?.issue_id ?? activeRatingThread?.next_issue_id

  // Fetch reader-context data when activeRatingThread changes
  useEffect(() => {
    if (!activeRatingThread || !issueId) {
      setReaderContext(null)
      return
    }

    const fetchReaderContext = async () => {
      setIsLoadingReaderContext(true)
      setReaderContextError(null)
      try {
        const response = await issuesApi.getReaderContext(issueId)
        setReaderContext(response)
      } catch (error) {
        console.error('Failed to fetch reader-context:', error)
        setReaderContextError('Failed to load reading context')
        setReaderContext(null)
      } finally {
        setIsLoadingReaderContext(false)
      }
    }

    fetchReaderContext()
  }, [activeRatingThread, issueId])

  return (
    <div className="w-full space-y-4">
      <div className="flex items-center gap-2 border-b-2 pb-2" style={{ borderColor: 'var(--theme-continuity-accent)' }}>
        <span className="text-[10px] font-black tabular-nums" style={{ color: 'var(--theme-continuity-accent)' }}>02</span>
        <span className="text-[10px] font-black uppercase tracking-[0.18em]" style={{ color: 'var(--theme-continuity-accent)' }}>Reading Context</span>
      </div>
      <ContinuityReadinessSummary issueId={issueId} />

      {/* Three-up status row: roll/result, series progress, readiness/eligibility */}
      <section className="grid grid-cols-3 gap-4 text-center pb-3 border-b border-[rgba(6,182,212,0.2)]">
        {/* Roll/Result */}
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
        
        {/* Series Progress */}
        <div>
          <div className="text-[9px] font-bold text-stone-500">Series Progress</div>
          <ReadingOrderGroups threadId={activeRatingThread?.id} className="text-[11px] font-mono text-amber-500" />
        </div>
        
        {/* Readiness/Eligibility */}
        <div>
          <div className="text-[9px] font-bold text-stone-500">Readiness</div>
          {/* We'll show a simplified version here, with details in ContinuityReadinessSummary above */}
          {issueId ? (
            <ContinuityReadinessSummary issueId={issueId} className="text-[11px]" />
          ) : (
            <span className="text-[11px] text-stone-400">—</span>
          )}
        </div>
      </section>

{/* Bounded local series chain */}
       {readerContext ? (
        <section aria-labelledby="local-series-heading" className="rounded-2xl p-4" style={{ border: '1px solid rgba(6,182,212,0.3)', backgroundColor: 'rgba(6, 182, 212, 0.09)' }}>
          <div className="flex items-center justify-between gap-2 mb-3">
            <h3 id="local-series-heading" className="text-[10px] font-black uppercase tracking-[0.18em]" style={{ color: 'var(--theme-continuity-accent)' }}>
              Local Series Chain
            </h3>
            {isLoadingReaderContext && <span className="text-[10px] text-stone-500">Loading...</span>}
            {readerContextError && <span className="text-[10px] text-red-500">{readerContextError}</span>}
          </div>
          
          <div className="space-y-2">
            {readerContext.local_chain.issues.map((issue, index) => {
              const isCurrent = issue.relation === 'current'
              return (
                <div key={issue.issue_id} className={`flex items-center gap-3 ${isCurrent ? 'border-l-2 border-l-solid border-l-[var(--theme-continuity-accent)]' : ''} `}>
                  {/* Issue relation indicator */}
                  <div className="flex-shrink-0 w-2 h-2 rounded-full" style={{
                    backgroundColor: isCurrent ? 'var(--theme-continuity-accent)' : 
                                issue.relation === 'previous' ? 'rgba(6,182,212,0.3)' :
                                issue.relation === 'next' ? 'rgba(6,182,212,0.2)' :
                                'rgba(6,182,212,0.1)'
                  }}></div>
                  
                  {/* Issue info */}
                  <div className="flex-1 space-y-1">
                    <div className="flex items-center justify-between">
                      <div className="flex-1">
                        <div className="flex items-center gap-2">
                          <span className="font-mono text-[10px]">{issue.issue_number}</span>
                          {issue.effective_rating !== null && (
                            <span className="text-[9px] text-stone-500">({issue.effective_rating})</span>
                          )}
                        </div>
                      </div>
                      <div className="text-[9px] text-stone-500">
                        {issue.relation === 'previous' && '←'}
                        {issue.relation === 'current' && 'YOU ARE HERE'}
                        {issue.relation === 'next' && '→'}
                        {issue.relation === 'future' && '↗'}
                      </div>
                    </div>
                    
                    {/* Crossover memberships for this issue (exact current/future crossover context) */}
                    {issue.crossover_memberships.length > 0 && (
                      <div className="flex flex-wrap gap-1 mt-1">
                        {issue.crossover_memberships.map((crossover) => (
                          <span key={crossover.id} className="rounded-full px-1.5 py-0.5 text-[8px] font-bold" style={{
                            border: '1px solid rgba(212,137,14,0.4)',
                            backgroundColor: 'rgba(212, 137, 14, 0.12)',
                            color: 'rgb(250, 204, 139)',
                          }}>
                            {crossover.name}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </section>
      ) : null}

      {/* Exact current/future crossover context attached to the issue that owns it */}
      {readerContext ? (
        <section aria-labelledby="exact-crossover-heading" className="rounded-2xl p-4" style={{ border: '1px solid rgba(6,182,212,0.3)', backgroundColor: 'rgba(6, 182, 212, 0.09)' }}>
          <div className="flex items-center justify-between gap-2 mb-3">
            <h3 id="exact-crossover-heading" className="text-[10px] font-black uppercase tracking-[0.18em]" style={{ color: 'var(--theme-continuity-accent)' }}>
              Exact Crossover Context
            </h3>
          </div>
          
          {/* Current issue crossovers */}
          <div className="space-y-2">
            <div className="font-bold text-[9px] text-stone-500 mb-1">Current Issue Crossovers:</div>
{readerContext.local_chain.issues
               .find(issue => issue.relation === 'current')
               ?.crossover_memberships.map((crossover) => (
                 <div key={crossover.id} className="rounded-full px-2 py-1 text-[9px] font-bold" style={{
                   border: '1px solid rgba(212,137,14,0.4)',
                   backgroundColor: 'rgba(212, 137, 14, 0.12)',
                   color: 'rgb(250, 204, 139)',
                 }}>
                   {crossover.name}
                 </div>
               )) || []}
          </div>
{/* Future crossovers (from crossovers array where applies_to_current_issue is false)} */
          <section aria-labelledby="upcoming-crossover-heading" className="rounded-2xl p-4" style={{ border: '1px solid rgba(6,182,212,0.3)', backgroundColor: 'rgba(6, 182, 212, 0.09)' }}>
            <div className="flex items-center justify-between gap-2 mb-3">
              <h3 id="upcoming-crossover-heading" className="text-[10px] font-black uppercase tracking-[0.18em]" style={{ color: 'var(--theme-continuity-accent)' }}>
                Upcoming Crossovers
              </h3>
              <span className="text-[8px] text-stone-500">
                ({readerContext.crossovers.filter(c => !c.applies_to_current_issue).length} upcoming)
              </span>
            </div>
            
            {readerContext.crossovers
              .filter(crossover => !crossover.applies_to_current_issue)
              .map((crossover) => (
                <div key={crossover.id} className="flex items-center gap-3 px-2 py-1" style={{ borderLeft: '3px solid rgb(250, 204, 139)', backgroundColor: 'rgba(250, 204, 139, 0.05)' }}>
                  <div className="flex-shrink-0 w-2 h-2 rounded-full" style={{ backgroundColor: 'rgb(250, 204, 139)' }}></div>
                  <div className="flex-1 space-y-0.5">
                    <div className="flex items-center justify-between text-[8px]">
                      <span>{crossover.name}</span>
                      <span className="text-stone-400">→</span>
                      <span>#{crossover.next_member?.issue_number ?? '?'}</span>
                    </div>
                  </div>
                </div>
              )) || []}
{readerContext.local_chain.edges.length > 0 ? (
            <div className="space-y-1">
              {readerContext.local_chain.edges.map((edge, index) => (
                <div key={edge.source_issue_id}-{edge.target_issue_id} className="flex items-center gap-3 px-2 py-1" style={{
                  borderLeft: edge.dependency_type === 'dependency' ? '3px solid rgb(250, 204, 139)' : '3px solid rgb(165, 243, 252)',
                  backgroundColor: edge.dependency_type === 'dependency' ? 'rgba(250, 204, 139, 0.05)' : 'rgba(165, 243, 252, 0.05)'
                }}>
                  <div className="flex-shrink-0 w-2 h-2 rounded-full" style={{
                    backgroundColor: edge.dependency_type === 'dependency' ? 'rgb(250, 204, 139)' : 'rgb(165, 243, 252)'
                  }}></div>
                  <div className="flex-1 space-y-0.5">
                    <div className="flex items-center justify-between text-[8px]">
                      <span>#{edge.source_issue_number}</span>
                      <span className="text-stone-400">{edge.dependency_type === 'dependency' ? '→' : '↝'}</span>
                      <span>#{edge.target_issue_number}</span>
                    </div>
                    {edge.note && (
                      <div className="text-[8px] text-stone-400 italic">
                        {edge.note}
                      </div>
                    )}
                  </div>
                }))
              }}
            </div>
          ) : (
            <p className="text-[9px] text-stone-500 text-center py-4">
              No dependency or continuity edges in local neighborhood
            </p>
          )}
        </section>
      ) : null}
        </section>
      ) : null}

      {/* Exact persisted one-hop dependency/continuity edges touching the local neighborhood */}
      {readerContext ? (
        <section aria-labelledby="dependency-edges-heading" className="rounded-2xl p-4" style={{ border: '1px solid rgba(6,182,212,0.3)', backgroundColor: 'rgba(6, 182, 212, 0.09)' }}>
          <div className="flex items-center justify-between gap-2 mb-3">
            <h3 id="dependency-edges-heading" className="text-[10px] font-black uppercase tracking-[0.18em]" style={{ color: 'var(--theme-continuity-accent)' }}>
              Dependency & Continuity Edges
            </h3>
            <span className="text-[8px] text-stone-500">
              ({readerContext.local_chain.edges.length} edges)
            </span>
          </div>
          
{readerContext.local_chain.edges.length > 0 ? (
            <div className="space-y-1">
              {readerContext.local_chain.edges.map((edge, index) => (
                <div key={edge.source_issue_id}-{edge.target_issue_id} className="flex items-center gap-3 px-2 py-1" style={{
                  borderLeft: edge.dependency_type === 'dependency' ? '3px solid rgb(250, 204, 139)' : '3px solid rgb(165, 243, 252)',
                  backgroundColor: edge.dependency_type === 'dependency' ? 'rgba(250, 204, 139, 0.05)' : 'rgba(165, 243, 252, 0.05)'
                }}>
                  <div className="flex-shrink-0 w-2 h-2 rounded-full" style={{
                    backgroundColor: edge.dependency_type === 'dependency' ? 'rgb(250, 204, 139)' : 'rgb(165, 243, 252)'
                  }}></div>
                  <div className="flex-1 space-y-0.5">
                    <div className="flex items-center justify-between text-[8px]">
                      <span>#{edge.source_issue_number}</span>
                      <span className="text-stone-400">{edge.dependency_type === 'dependency' ? '→' : '↝'}</span>
                      <span>#{edge.target_issue_number}</span>
                    </div>
                    {edge.note && (
                      <div className="text-[8px] text-stone-400 italic">
                        {edge.note}
                      </div>
                    )}
                  </div>
                }))
              }}
            </div>
          ) : (
            <p className="text-[9px] text-stone-500 text-center py-4">
              No dependency or continuity edges in local neighborhood
            </p>
          )}
        </section>
      ) : null}

      {/* Retained reading-route summaries */}
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
            )}
          </div>
        </section>
      ) : null}

      {/* Explain route / correction affordances */}
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