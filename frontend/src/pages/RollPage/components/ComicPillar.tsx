import { useState } from 'react'
import { RATING_THRESHOLD, getProgressPercentage } from '../utils'
import type { RatingThread } from '../types'
import { ComicVineIssueCard } from './ComicVineIssueCard'
import { ContinuityReadinessSummary } from './ContinuityReadinessSummary'
import { ReadingOrderGroups } from './ReadingOrderGroups'
import { ReadingRouteExplanation } from './ReadingRouteExplanation'

interface ComicPillarProps {
  activeRatingThread: RatingThread | null
  currentDie: number
  rolledResult: number | null
  rating: number
  poolSize: number
  readingOrders: import('../../services/api-reading-orders').ReadingOrder[]
  connectedThreads: import('../../types').ConnectedThreadInfo[]
  onUpdateRating: (value: string) => void
  onSubmitRating: (finishSession: boolean) => void
  onSnooze: () => void
  onCancel: () => void
  onRefreshThread: () => void
}

export function ComicPillar({
  activeRatingThread,
  currentDie,
  rolledResult,
  rating,
  poolSize,
  readingOrders,
  connectedThreads,
  onUpdateRating,
  onSubmitRating,
  onSnooze,
  onCancel,
  onRefreshThread,
}: ComicPillarProps) {
  const [isCorrectionDialogOpen, setIsCorrectionDialogOpen] = useState(false)
  const [isContinuityDialogOpen, setIsContinuityDialogOpen] = useState(false)
  const [isRouteExplanationOpen, setIsRouteExplanationOpen] = useState(false)
  const [copyStatus, setCopyStatus] = useState<'idle' | 'copied' | 'failed'>('idle')
  const threadTitle = activeRatingThread?.title ?? 'Loading…'
  const issueNumber = activeRatingThread?.next_issue_number ?? activeRatingThread?.issue_number ?? null
  const issueId = activeRatingThread?.issue_id ?? activeRatingThread?.next_issue_id
  const totalIssues = activeRatingThread?.total_issues ?? null
  const issuesRemaining = activeRatingThread?.issues_remaining ?? 0
  const progress = getProgressPercentage(activeRatingThread)

  async function handleCopyComicReference() {
    if (!activeRatingThread?.title || issueNumber == null) return

    try {
      await navigator.clipboard.writeText(`${activeRatingThread.title} ${issueNumber}`)
      setCopyStatus('copied')
    } catch {
      setCopyStatus('failed')
    }
  }

  return (
    <div className="w-full space-y-4">
      <section id="thread-info" aria-labelledby="selected-issue-heading" className="space-y-3">
        <div className="rounded-2xl border border-white/10 bg-white/[0.04] p-3 md:p-4">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="text-[10px] font-black uppercase tracking-[0.18em] text-stone-500">
                Selected issue
              </p>
              <h2 id="selected-issue-heading" className="mt-1 text-xl font-black leading-tight text-stone-100">
                {threadTitle}
                {issueNumber != null ? <span className="text-amber-400"> #{issueNumber}</span> : null}
              </h2>
              {hasValidRolledResult ? (
                <p className="mt-1 text-[11px] font-bold text-stone-400">
                  Rolled {rolledResult} on d{currentDie}
                  {currentDie > poolSize ? ` · ${poolSize} eligible` : ''}
                </p>
              ) : null}
            </div>
            {issueNumber != null ? (
              <div className="flex shrink-0 gap-1.5">
                <button
                  type="button"
                  onClick={handleCopyComicReference}
                  disabled={!activeRatingThread?.title}
                  className="min-h-11 rounded-xl border border-white/10 bg-white/5 px-3 text-[10px] font-black uppercase tracking-wider text-stone-300 transition hover:bg-white/10 focus:ring-2 focus:ring-amber-500 disabled:opacity-30"
                  aria-label={`Copy ${threadTitle} ${issueNumber}`}
                >
                  {copyStatus === 'copied' ? 'Copied' : copyStatus === 'failed' ? 'Retry copy' : 'Copy'}
                </button>
                <button
                  type="button"
                  onClick={() => setIsCorrectionDialogOpen(true)}
                  disabled={!activeRatingThread?.id}
                  className="min-h-11 rounded-xl border border-white/10 bg-white/5 px-3 text-[10px] font-black uppercase tracking-wider text-stone-300 transition hover:bg-white/10 focus:ring-2 focus:ring-amber-500 disabled:opacity-30"
                  aria-label="Correct issue number"
                >
                  Edit
                </button>
              </div>
            ) : null}
          </div>

          {copyStatus === 'failed' ? (
            <p className="mt-2 text-[10px] font-bold text-rose-400" role="status">
              Copy failed. Use Retry copy to try again.
            </p>
          ) : null}

          <div className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] font-bold text-stone-500">
            {totalIssues && issueNumber != null ? (
              <span>Issue {issueNumber} of {totalIssues}</span>
            ) : null}
            {totalIssues && issueNumber != null ? <span aria-hidden="true">·</span> : null}
            <span>{progress}% complete</span>
            <span aria-hidden="true">·</span>
            <span>{issuesRemaining} left</span>
          </div>
        </div>
      </section>

      {connectedThreads.length > 0 ? (
        <section aria-labelledby="connected-heading" className="rounded-2xl border border-blue-800/30 bg-blue-950/15 p-3">
          <div className="flex items-center justify-between gap-2">
            <h3 id="connected-heading" className="text-[10px] font-black uppercase tracking-[0.18em] text-blue-400">
              Verified dependency connections
            </h3>
            <button
              type="button"
              onClick={() => setIsContinuityDialogOpen(true)}
              className="text-[10px] font-bold text-blue-400 hover:text-blue-300 transition-colors"
            >
              Correct continuity
            </button>
          </div>
          <ul className="mt-2 flex flex-wrap gap-1.5" aria-label="Connected threads">
            {connectedThreads.map((connectedThread) => (
              <li
                key={`${connectedThread.thread_id}-${connectedThread.dependency_id}`}
                className="rounded-full border border-blue-800/40 bg-blue-900/20 px-2.5 py-1 text-[10px] font-bold text-blue-200"
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
            <h3 id="routes-heading" className="text-[10px] font-black uppercase tracking-[0.18em] text-stone-500">
              Reading routes
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
                <article key={order.id} className="rounded-xl border border-white/10 bg-white/[0.04] p-3">
                  <div className="flex items-center justify-between gap-3">
                    <h4 className="truncate text-xs font-black text-stone-200">{order.name}</h4>
                    <span className="shrink-0 text-[10px] font-bold text-stone-500">
                      {order.completed_items}/{order.total_items}
                    </span>
                  </div>
                  <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-white/10" aria-hidden="true">
                    <div className="h-full rounded-full bg-amber-600" style={{ width: `${routeProgress}%` }} />
                  </div>
                  <div className="mt-2 flex items-center justify-between gap-2">
                    <p className="text-[10px] font-bold text-stone-500">{routeProgress}% complete</p>
                    <button
                      type="button"
                      onClick={() => setIsRouteExplanationOpen(true)}
                      className="min-h-11 rounded-lg border border-amber-700/40 bg-amber-900/15 px-3 text-[10px] font-black text-amber-200 focus:ring-2 focus:ring-amber-500"
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

      <ContinuityReadinessSummary issueId={issueId} />
    </div>
  )
}