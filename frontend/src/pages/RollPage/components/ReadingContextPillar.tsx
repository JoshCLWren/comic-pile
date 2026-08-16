import { useState, useEffect, useCallback } from 'react'
import { ContinuityReadinessSummary } from './ContinuityReadinessSummary'
import { ReadingOrderGroups } from './ReadingOrderGroups'
import { ReadingRouteExplanation } from './ReadingRouteExplanation'
import {
  readerContextApi,
  type ReaderContextResponse,
  type LocalChainIssue,
  type LocalChainEdge,
  type CrossoverInfo,
} from '../../../services/api-reader-context'
import Tooltip from '../../../components/Tooltip'
import type { RatingThread } from '../types'
import type { ReadingOrder } from '../../../services/api-reading-orders'
import type { ConnectedThreadInfo } from '../../../types'

interface ReadingContextPillarProps {
  activeRatingThread: RatingThread | null
  issueId: number | null
  readingOrders: ReadingOrder[]
  connectedThreads: ConnectedThreadInfo[]
}

export function ReadingContextPillar({
  activeRatingThread,
  issueId,
  readingOrders,
  connectedThreads,
}: ReadingContextPillarProps) {
  const [readerContext, setReaderContext] = useState<ReaderContextResponse | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [isRouteExplanationOpen, setIsRouteExplanationOpen] = useState(false)

  const fetchReaderContext = useCallback(async () => {
    if (!issueId) {
      setReaderContext(null)
      return
    }
    setIsLoading(true)
    setError(null)
    try {
      const data = await readerContextApi.getForIssue(issueId)
      setReaderContext(data)
    } catch (err) {
      setError('Failed to load reading context')
      console.error('Reader context fetch failed:', err)
    } finally {
      setIsLoading(false)
    }
  }, [issueId])

  useEffect(() => {
    fetchReaderContext()
  }, [fetchReaderContext])

  const threadTitle = activeRatingThread?.title ?? 'Loading…'
  const issueNumber =
    activeRatingThread?.next_issue_number ?? activeRatingThread?.issue_number ?? null

  if (isLoading) {
    return (
      <section
        aria-labelledby="reading-context-heading"
        className="space-y-4 p-4 md:p-6"
        role="status"
        aria-live="polite"
      >
        <h2
          id="reading-context-heading"
          className="text-[10px] font-black uppercase tracking-[0.18em] text-cyan-500"
        >
          02 READING CONTEXT
        </h2>
        <div className="py-8 text-center text-stone-500">
          <span className="text-[10px] font-bold uppercase tracking-wider">
            Loading reading context…
          </span>
        </div>
      </section>
    )
  }

  if (error) {
    return (
      <section
        aria-labelledby="reading-context-heading"
        className="space-y-4 p-4 md:p-6"
        role="alert"
      >
        <h2
          id="reading-context-heading"
          className="text-[10px] font-black uppercase tracking-[0.18em] text-cyan-500"
        >
          02 READING CONTEXT
        </h2>
        <div className="rounded-2xl border border-rose-700/30 bg-rose-950/20 p-4">
          <p className="text-[11px] text-rose-200">{error}</p>
          <button
            type="button"
            onClick={fetchReaderContext}
            className="mt-3 min-h-11 rounded-xl border border-rose-700/40 bg-rose-900/20 px-4 text-xs font-black text-rose-200 hover:bg-rose-900/35 focus:ring-2 focus:ring-rose-500"
          >
            Retry
          </button>
        </div>
        <ContinuityReadinessSummary issueId={issueId} />
        <ReadingOrderGroups threadId={activeRatingThread?.id} />
      </section>
    )
  }

  const currentIssue = readerContext?.local_chain.issues.find((i) => i.relation === 'current')
  const edges = readerContext?.local_chain.edges ?? []
  const crossovers = readerContext?.crossovers ?? []
  const series = readerContext?.series

  return (
    <section aria-labelledby="reading-context-heading" className="space-y-4 p-4 md:p-6">
      <h2
        id="reading-context-heading"
        className="text-[10px] font-black uppercase tracking-[0.18em] text-cyan-500"
      >
        02 READING CONTEXT
      </h2>

      <div className="space-y-4 rounded-2xl border border-white/10 bg-white/[0.04] p-3 md:p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-xs font-black text-stone-200">
              {threadTitle}
              {issueNumber != null ? <span className="text-amber-400"> #{issueNumber}</span> : null}
            </p>
            {currentIssue && (
              <p className="mt-1 text-[11px] font-bold text-stone-400">
                Issue {currentIssue.issue_number} · Position {currentIssue.position}
              </p>
            )}
          </div>
          <button
            type="button"
            onClick={() => setIsRouteExplanationOpen(true)}
            className="min-h-11 shrink-0 rounded-xl border border-cyan-700/40 bg-cyan-900/15 px-3 text-[10px] font-black uppercase tracking-wider text-cyan-200 hover:bg-cyan-900/25 focus:ring-2 focus:ring-cyan-500"
          >
            Explain Route
          </button>
        </div>

        <ContinuityReadinessSummary issueId={issueId} />

        {series && series.identity_source === 'comicvine' && (
          <div className="space-y-2 rounded-xl border border-amber-700/30 bg-amber-900/10 p-3">
            <p className="text-[10px] font-black uppercase tracking-[0.18em] text-amber-400">
              Series Analytics
            </p>
            <div className="grid grid-cols-2 gap-2 text-center md:grid-cols-4">
              <div>
                <p className="text-2xl font-black text-amber-300">
                  {series.average_rating?.toFixed(2) ?? '—'}
                </p>
                <p className="text-[10px] font-bold text-stone-500">Avg Rating</p>
              </div>
              <div>
                <p className="text-2xl font-black text-amber-300">{series.ratings_count}</p>
                <p className="text-[10px] font-bold text-stone-500">Rated Issues</p>
              </div>
              <div>
                <p className="text-2xl font-black text-amber-300">
                  {series.highest_rating?.toFixed(1) ?? '—'}
                </p>
                <p className="text-[10px] font-bold text-stone-500">Highest</p>
              </div>
              <div>
                <p className="text-2xl font-black text-amber-300">
                  {series.lowest_rating?.toFixed(1) ?? '—'}
                </p>
                <p className="text-[10px] font-bold text-stone-500">Lowest</p>
              </div>
            </div>
          </div>
        )}

        {crossovers.length > 0 && (
          <div className="space-y-2">
            <p className="text-[10px] font-black uppercase tracking-[0.18em] text-stone-500">
              Crossover Context
            </p>
            <div className="flex flex-wrap gap-2">
              {crossovers.map((crossover) => (
                <CrossoverBadge key={crossover.id} crossover={crossover} />
              ))}
            </div>
          </div>
        )}

        <div className="border-t border-white/10 pt-4">
          <p className="mb-3 text-[10px] font-black uppercase tracking-[0.18em] text-stone-500">
            Local Reading Chain
          </p>
          <LocalChainView
            issues={readerContext?.local_chain.issues ?? []}
            edges={edges}
            currentIssueId={currentIssue?.issue_id}
          />
        </div>

        {edges.length > 0 && (
          <div className="border-t border-white/10 pt-4">
            <p className="mb-3 text-[10px] font-black uppercase tracking-[0.18em] text-stone-500">
              Hard Dependencies (One-Hop)
            </p>
            <ul className="space-y-2" aria-label="Hard dependency edges">
              {edges.map((edge) => (
                <li
                  key={edge.dependency_id}
                  className="rounded-xl border border-rose-700/40 bg-rose-900/20 p-3"
                >
                  <div className="flex items-center gap-2 text-[11px]">
                    <span className="font-bold text-rose-200">
                      {edge.source_thread_title} #{edge.source_issue_number}
                    </span>
                    <span className="text-rose-400" aria-hidden="true">
                      →
                    </span>
                    <span className="font-bold text-rose-200">
                      {edge.target_thread_title} #{edge.target_issue_number}
                    </span>
                    {edge.note && <span className="ml-auto text-stone-500">{edge.note}</span>}
                  </div>
                  <p className="mt-1 text-[10px] text-stone-500">
                    Hard dependency · Edge #{edge.dependency_id}
                  </p>
                </li>
              ))}
            </ul>
          </div>
        )}

        <ReadingOrderGroups threadId={activeRatingThread?.id} />

        {readingOrders.length > 0 && (
          <div className="border-t border-white/10 pt-4">
            <p className="mb-2 text-[10px] font-black uppercase tracking-[0.18em] text-stone-500">
              Reading Routes
            </p>
            <div className="grid gap-2 md:grid-cols-2">
              {readingOrders.map((order) => {
                const routeProgress =
                  order.total_items > 0
                    ? Math.round((order.completed_items / order.total_items) * 100)
                    : 0
                return (
                  <article
                    key={order.id}
                    className="rounded-xl border border-blue-800/30 bg-blue-950/15 p-3"
                  >
                    <p className="text-sm font-black text-blue-100">{order.name}</p>
                    <p className="mt-1 text-[11px] text-stone-400">
                      {order.completed_items} of {order.total_items} complete · {routeProgress}%
                    </p>
                  </article>
                )
              })}
            </div>
          </div>
        )}

        <button
          type="button"
          onClick={() => setIsRouteExplanationOpen(true)}
          className="min-h-11 w-full rounded-xl border border-cyan-700/40 bg-cyan-900/15 px-4 text-xs font-black uppercase tracking-wider text-cyan-200 hover:bg-cyan-900/25 focus:ring-2 focus:ring-cyan-500"
        >
          View Full Dependency Graph
        </button>
      </div>

      <ReadingRouteExplanation
        isOpen={isRouteExplanationOpen}
        issueId={issueId}
        issueLabel={`${threadTitle}${issueNumber != null ? ` #${issueNumber}` : ''}`}
        readingOrders={readingOrders}
        connectedThreads={connectedThreads}
        onClose={() => setIsRouteExplanationOpen(false)}
      />
    </section>
  )
}

function CrossoverBadge({ crossover }: { crossover: CrossoverInfo }) {
  const appliesToCurrent = crossover.applies_to_current_issue
  const nextMember = crossover.next_member

  return (
    <Tooltip
      content={
        appliesToCurrent
          ? `This issue is part of ${crossover.name}`
          : nextMember
            ? `${crossover.name} continues at #${nextMember.issue_number}`
            : crossover.name
      }
    >
      <div
        className={`rounded-xl border px-3 py-2 text-xs font-black ${
          appliesToCurrent
            ? 'border-cyan-700/40 bg-cyan-900/20 text-cyan-200'
            : 'border-amber-700/40 bg-amber-900/15 text-amber-200'
        }`}
      >
        <span className="font-bold">{crossover.name}</span>
        {appliesToCurrent ? (
          <span className="ml-1.5 text-cyan-400">⟶ MEMBER</span>
        ) : nextMember ? (
          <span className="ml-1.5 text-amber-400">→ #{nextMember.issue_number}</span>
        ) : null}
        <span className="ml-1.5 text-stone-500">
          ({crossover.read_count}/{crossover.ratings_count})
        </span>
      </div>
    </Tooltip>
  )
}

function LocalChainView({
  issues,
  edges,
  currentIssueId,
}: {
  issues: LocalChainIssue[]
  edges: LocalChainEdge[]
  currentIssueId: number | undefined
}) {
  if (issues.length === 0) {
    return (
      <p className="py-4 text-center text-[11px] text-stone-500">
        No local chain data available
      </p>
    )
  }

  return (
    <div className="relative" role="list" aria-label="Local reading chain">
      <div
        className="absolute left-8 top-0 bottom-0 w-0.5 bg-white/10 md:left-10"
        aria-hidden="true"
      />
      <ul className="relative space-y-3" role="list">
        {issues.map((issue, index) => (
          <LocalChainNode
            key={issue.issue_id}
            issue={issue}
            isCurrent={issue.issue_id === currentIssueId}
            index={index}
            total={issues.length}
            hasEdgeToNext={edges.some(
              (e) =>
                e.source_issue_id === issue.issue_id ||
                e.target_issue_id === issue.issue_id,
            )}
          />
        ))}
      </ul>
    </div>
  )
}

function LocalChainNode({
  issue,
  isCurrent,
  index,
  total,
  hasEdgeToNext: _hasEdgeToNext,
}: {
  issue: LocalChainIssue
  isCurrent: boolean
  index: number
  total: number
  hasEdgeToNext: boolean
}) {
  const isLast = index === total - 1

  return (
    <li className="group relative flex items-start gap-3" role="listitem">
      <div className="relative z-10 flex h-4 w-4 flex-shrink-0 items-center justify-center md:h-5 md:w-5">
        <div
          className={`h-2.5 w-2.5 rounded-full border-2 transition-all md:h-3 md:w-3 ${
            isCurrent
              ? 'border-amber-400 bg-amber-400 ring-2 ring-amber-400/30'
              : issue.status === 'read'
                ? 'border-emerald-500 bg-emerald-500'
                : 'border-stone-500 bg-stone-700'
          }`}
          aria-hidden="true"
        />
        {!isLast && (
          <div
            className="absolute left-1/2 top-full w-0.5 bg-white/10"
            style={{ bottom: '-1.5rem' }}
            aria-hidden="true"
          />
        )}
      </div>
      <div className={`min-w-0 flex-1 ${isCurrent ? 'md:ml-2' : 'md:ml-0'}`}>
        <div
          className={`rounded-xl border p-3 transition-colors ${
            isCurrent
              ? 'border-amber-500/50 bg-amber-900/20'
              : 'border-white/10 bg-white/[0.04] hover:border-white/20'
          }`}
        >
          <div className="flex items-center gap-2">
            {isCurrent && (
              <Tooltip content="You are here">
                <span className="rounded bg-amber-900/30 px-1.5 py-0.5 text-[9px] font-black uppercase tracking-wider text-amber-400">
                  YOU ARE HERE
                </span>
              </Tooltip>
            )}
            <span
              className={`text-xs font-black ${
                isCurrent
                  ? 'text-amber-300'
                  : issue.status === 'read'
                    ? 'text-emerald-300'
                    : 'text-stone-200'
              }`}
            >
              #{issue.issue_number}
            </span>
            {issue.rating != null && (
              <span
                className={`text-[10px] font-bold ${
                  issue.rating >= 3.5 ? 'text-amber-400' : 'text-rose-400'
                }`}
              >
                {issue.rating.toFixed(1)}
              </span>
            )}
            {issue.crossover_memberships.length > 0 && (
              <span className="ml-auto flex items-center gap-1">
                {issue.crossover_memberships.map((cm) => (
                  <Tooltip key={cm.issue_id} content={`Crossover member: ${cm.issue_number}`}>
                    <span className="text-[10px] font-bold text-cyan-400/80" aria-hidden="true">
                      ⟡
                    </span>
                  </Tooltip>
                ))}
              </span>
            )}
          </div>
          {issue.crossover_memberships.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1">
              {issue.crossover_memberships.map((cm) => (
                <span
                  key={cm.issue_id}
                  className="rounded bg-cyan-900/20 px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider text-cyan-400/80"
                >
                  {cm.issue_number}
                </span>
              ))}
            </div>
          )}
        </div>
        {isCurrent && (
          <Tooltip content="Current issue in the reading chain">
            <span className="absolute -left-10 top-1/2 -translate-y-1/2 whitespace-nowrap text-[9px] font-black uppercase tracking-wider text-amber-400 opacity-0 transition-opacity group-hover:opacity-100 md:-left-14">
              ← CURRENT
            </span>
          </Tooltip>
        )}
      </div>
    </li>
  )
}
