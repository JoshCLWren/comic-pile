import { useState } from 'react'
import type { ReadingOrder } from '../../../services/api-reading-orders'
import type { ConnectedThreadInfo } from '../../../types'
import { ContinuityReadinessSummary } from './ContinuityReadinessSummary'
import { ReadingOrderGroups } from './ReadingOrderGroups'
import { ReadingRouteExplanation } from './ReadingRouteExplanation'
import type { RatingThread } from '../types'
import { PillarFrame } from './PillarFrame'

interface ReadingContextPillarProps {
  activeRatingThread: RatingThread | null
  issueId: number | null | undefined
  currentDie: number
  rolledResult: number | null
  poolSize: number
  hasValidRolledResult: boolean
  readingOrders: ReadingOrder[]
  connectedThreads: ConnectedThreadInfo[]
  onCopyIssue: () => void
  onCopyStatus: 'idle' | 'copied' | 'failed'
  onEditIssue: () => void
  onCorrectContinuity: () => void
  onRefreshThread: () => void
  onRouteExplanationOpen: () => void
}

export function ReadingContextPillar({
  activeRatingThread,
  issueId,
  currentDie,
  rolledResult,
  poolSize,
  hasValidRolledResult,
  readingOrders,
  connectedThreads,
  onCopyIssue,
  onCopyStatus,
  onEditIssue,
  onCorrectContinuity,
  onRefreshThread,
  onRouteExplanationOpen,
}: ReadingContextPillarProps) {
  const threadTitle = activeRatingThread?.title ?? 'Loading…'
  const issueNumber = activeRatingThread?.next_issue_number ?? activeRatingThread?.issue_number ?? null
  const totalIssues = activeRatingThread?.total_issues ?? null
  const issuesRemaining = activeRatingThread?.issues_remaining ?? 0
  const progress = totalIssues && totalIssues > 0
    ? Math.round(((totalIssues - (issuesRemaining || 0)) / totalIssues) * 100)
    : 0

  return (
    <PillarFrame
      number="02"
      title="READING CONTEXT"
      accent="reading"
      subtitle="continuity command center"
    >
      <div className="space-y-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-xl font-black leading-tight" style={{ color: 'var(--theme-text-primary)' }}>
              {threadTitle}
              {issueNumber != null ? <span style={{ color: 'var(--theme-continuity-accent)' }}> #{issueNumber}</span> : null}
            </h2>
            {hasValidRolledResult ? (
              <p className="mt-1 text-[11px] font-bold" style={{ color: 'var(--theme-text-muted)' }}>
                Rolled {rolledResult} on d{currentDie}
                {currentDie > poolSize ? ` · ${poolSize} eligible` : ''}
              </p>
            ) : null}
          </div>
          {issueNumber != null ? (
            <div className="flex shrink-0 gap-1.5">
              <button
                type="button"
                onClick={onCopyIssue}
                disabled={!activeRatingThread?.title}
                className="min-h-11 rounded-xl border border-[var(--theme-panel-border)] bg-white/5 px-3 text-[10px] font-black uppercase tracking-wider text-stone-300 transition hover:bg-white/10 focus:ring-2 focus:ring-[var(--theme-continuity-accent)] disabled:opacity-30"
                aria-label={`Copy ${threadTitle} ${issueNumber}`}
              >
                {onCopyStatus === 'copied' ? 'Copied' : onCopyStatus === 'failed' ? 'Retry copy' : 'Copy'}
              </button>
              <button
                type="button"
                onClick={onEditIssue}
                disabled={!activeRatingThread?.id}
                className="min-h-11 rounded-xl border border-[var(--theme-panel-border)] bg-white/5 px-3 text-[10px] font-black uppercase tracking-wider text-stone-300 transition hover:bg-white/10 focus:ring-2 focus:ring-[var(--theme-continuity-accent)] disabled:opacity-30"
                aria-label="Correct issue number"
              >
                Edit
              </button>
            </div>
          ) : null}
        </div>

        {onCopyStatus === 'failed' ? (
          <p className="text-[10px] font-bold" style={{ color: 'var(--theme-danger)' }} role="status">
            Copy failed. Use Retry copy to try again.
          </p>
        ) : null}

        <div
          className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] font-bold"
          style={{ color: 'var(--theme-text-muted)' }}
        >
          {totalIssues && issueNumber != null ? (
            <span>Issue {issueNumber} of {totalIssues}</span>
          ) : null}
          {totalIssues && issueNumber != null ? <span aria-hidden="true">·</span> : null}
          <span>{progress}% complete</span>
          <span aria-hidden="true">·</span>
          <span>{issuesRemaining} left</span>
        </div>

        <ContinuityReadinessSummary issueId={issueId} />

        {connectedThreads.length > 0 ? (
          <section aria-labelledby="connected-heading">
            <div className="flex items-center justify-between gap-2">
              <h3
                id="connected-heading"
                className="text-[10px] font-black uppercase tracking-[0.18em]"
                style={{ color: 'var(--theme-continuity-accent)' }}
              >
                Verified dependency connections
              </h3>
              <button
                type="button"
                onClick={onCorrectContinuity}
                className="text-[10px] font-bold transition-colors"
                style={{ color: 'var(--theme-continuity-accent)' }}
              >
                Correct continuity
              </button>
            </div>
            <ul className="mt-2 flex flex-wrap gap-1.5" aria-label="Connected threads">
              {connectedThreads.map((connectedThread) => (
                <li
                  key={`${connectedThread.thread_id}-${connectedThread.dependency_id}`}
                  className="rounded-full px-2.5 py-1 text-[10px] font-bold"
                  style={{
                    backgroundColor: 'rgba(34, 209, 178, 0.15)',
                    color: 'var(--theme-continuity-accent)',
                    borderColor: 'rgba(34, 209, 178, 0.25)',
                    border: '1px solid',
                  }}
                >
                  {connectedThread.title}
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        <ReadingOrderGroups threadId={activeRatingThread?.id} />

        {readingOrders.length > 0 ? (
          <section aria-labelledby="routes-heading" className="space-y-2">
            <div className="flex items-center justify-between gap-2">
              <h3
                id="routes-heading"
                className="text-[10px] font-black uppercase tracking-[0.18em]"
                style={{ color: 'var(--theme-text-muted)' }}
              >
                Reading routes
              </h3>
              <span className="text-[10px] font-bold" style={{ color: 'var(--theme-text-dim)' }}>
                {readingOrders.length} active
              </span>
            </div>
            <div className="grid gap-2 md:grid-cols-2">
              {readingOrders.map((order) => {
                const routeProgress = order.total_items > 0
                  ? Math.round((order.completed_items / order.total_items) * 100)
                  : 0
                return (
                  <article key={order.id} className="rounded-xl border border-[var(--theme-panel-border)] bg-white/[0.04] p-3">
                    <div className="flex items-center justify-between gap-3">
                      <h4 className="truncate text-xs font-black" style={{ color: 'var(--theme-text-primary)' }}>{order.name}</h4>
                      <span className="shrink-0 text-[10px] font-bold" style={{ color: 'var(--theme-text-muted)' }}>
                        {order.completed_items}/{order.total_items}
                      </span>
                    </div>
                    <div className="mt-2 h-1.5 overflow-hidden rounded-full" style={{ backgroundColor: 'rgba(255,255,255,0.10)' }} aria-hidden="true">
                      <div
                        className="h-full rounded-full"
                        style={{ width: `${routeProgress}%`, backgroundColor: 'var(--theme-comic-accent)' }}
                      />
                    </div>
                    <div className="mt-2 flex items-center justify-between gap-2">
                      <p className="text-[11px] font-bold" style={{ color: 'var(--theme-text-muted)' }}>{routeProgress}% complete</p>
                      <button
                        type="button"
                        onClick={onRouteExplanationOpen}
                        className="min-h-11 rounded-lg border border-[var(--theme-panel-border)] px-3 text-[10px] font-black transition-colors focus:ring-2"
                        style={{
                          backgroundColor: 'rgba(212, 137, 14, 0.08)',
                          color: 'var(--theme-comic-accent)',
                          '--tw-ring-color': 'var(--theme-comic-accent)',
                        } as React.CSSProperties}
                        aria-label={`Explain why ${threadTitle} ${issueNumber != null ? `#${issueNumber}` : ''} is next`}
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

        <section
          aria-label="Local reading chain"
          className="rounded-xl border border-dashed border-[var(--theme-panel-border)] p-3 text-center"
          data-testid="local-chain-placeholder"
        >
          <p className="text-[10px] font-black uppercase tracking-[0.18em]" style={{ color: 'var(--theme-text-muted)' }}>
            Local reading chain
          </p>
          <p className="mt-1 text-[11px]" style={{ color: 'var(--theme-text-dim)' }}>
            The local series chain and crossover membership for this issue will render here.
          </p>
        </section>

        <button
          type="button"
          onClick={onRouteExplanationOpen}
          className="w-full rounded-xl border border-[var(--theme-panel-border)] bg-white/5 px-3 py-2 text-[10px] font-black uppercase tracking-widest text-stone-300 transition hover:bg-white/10 focus:ring-2"
          style={{ '--tw-ring-color': 'var(--theme-continuity-accent)' } as React.CSSProperties}
        >
          View full dependency graph
        </button>
      </div>
    </PillarFrame>
  )
}
