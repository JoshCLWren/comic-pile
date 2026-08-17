import { useState } from 'react'
import IssueCorrectionDialog from '../../../components/IssueCorrectionDialog'
import ContinuityCorrectionDialog from '../../../components/ContinuityCorrectionDialog'
import Tooltip from '../../../components/Tooltip'
import type { ReadingOrder } from '../../../services/api-reading-orders'
import type {
  CanonicalSeriesInfo,
  ConnectedThreadInfo,
  CrossoverAnalyticsInfo,
  ReaderContextResponse,
} from '../../../types'
import { RATING_THRESHOLD, getProgressPercentage } from '../utils'
import type { RatingThread } from '../types'
import { ComicVineIssueCard } from './ComicVineIssueCard'
import { ContinuityReadinessSummary } from './ContinuityReadinessSummary'
import { ReadingOrderGroups } from './ReadingOrderGroups'
import { ReadingRouteExplanation } from './ReadingRouteExplanation'

function getDieDirection(currentDie: number, predictedDie: number): string {
  if (predictedDie < currentDie) return 'More focused next roll'
  if (predictedDie > currentDie) return 'More variety next roll'
  return 'Die stays the same'
}

interface RatingViewProps {
  activeRatingThread: RatingThread | null
  currentDie: number
  rolledResult: number | null
  rating: number
  predictedDie: number
  hasValidRolledResult: boolean
  poolSize: number
  errorMessage: string
  rateIsPending: boolean
  snoozeIsPending: boolean
  dismissIsPending: boolean
  readingOrders: ReadingOrder[]
  connectedThreads: ConnectedThreadInfo[]
  readerContext: ReaderContextResponse | null
  onUpdateRating: (value: string) => void
  onSubmitRating: (finishSession: boolean) => void
  onSnooze: () => void
  onCancel: () => void
  onRefreshThread: () => void
}

export function RatingView({
  activeRatingThread,
  currentDie,
  rolledResult,
  rating,
  predictedDie,
  hasValidRolledResult,
  poolSize,
  errorMessage,
  rateIsPending,
  snoozeIsPending,
  dismissIsPending,
  readingOrders,
  connectedThreads,
  readerContext,
  onUpdateRating,
  onSubmitRating,
  onSnooze,
  onCancel,
  onRefreshThread,
}: RatingViewProps) {
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
  const dieDirection = getDieDirection(currentDie, predictedDie)

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
    <div className="relative z-10 space-y-4 p-3 md:p-4">
      <section id="thread-info" aria-labelledby="selected-issue-heading" className="space-y-3">
        <div className="rounded-2xl border border-white/10 bg-white/[0.04] p-3">
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

        <ContinuityReadinessSummary issueId={issueId} />
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

      {readerContext != null ? (
        <>
          {readerContext.canonical_series != null ? (
            <section aria-labelledby="series-heading" className="rounded-2xl border border-white/10 bg-white/[0.04] p-3 space-y-2">
              <h3 id="series-heading" className="text-[10px] font-black uppercase tracking-[0.18em] text-stone-500">
                {readerContext.canonical_series.identity_source === 'unavailable'
                  ? 'Canonical series history unavailable'
                  : 'Canonical series'}
              </h3>
              {readerContext.canonical_series.identity_source !== 'unavailable' && (
                <>
                  <div className="flex items-baseline gap-x-2 gap-y-1">
                    <span className="text-lg font-black text-stone-100">
                      {readerContext.canonical_series.average_rating != null
                        ? readerContext.canonical_series.average_rating.toFixed(2)
                        : '—'}
                    </span>
                    <span className="text-[10px] font-bold text-stone-500">
                      {readerContext.canonical_series.rated_count} rated
                    </span>
                  </div>
                  {readerContext.canonical_series.previous_issue != null && (
                    <div className="text-[11px] font-bold text-stone-400">
                      <span>Previous: {readerContext.canonical_series.previous_issue.thread_title}
                        {' #'}{readerContext.canonical_series.previous_issue.issue_number}</span>
                      {readerContext.canonical_series.previous_issue.effective_rating != null && (
                        <span className="ml-1.5 text-stone-300">
                          ({readerContext.canonical_series.previous_issue.effective_rating.toFixed(1)})
                          {readerContext.canonical_series.previous_issue.is_read ? ' · read' : ''}
                        </span>
                      )}
                    </div>
                  )}
                  {readerContext.canonical_series.recent_ratings.length > 0 && (
                    <div className="space-y-0.5">
                      {readerContext.canonical_series.recent_ratings.map((entry, idx) => (
                        <div key={`${entry.thread_id}-${idx}`} className="flex items-baseline gap-x-2 text-[11px]">
                          <span className="font-black text-stone-200">{entry.rating.toFixed(1)}</span>
                          <span className="truncate font-bold text-stone-400">{entry.thread_title}</span>
                        </div>
                      ))}
                    </div>
                  )}
                  <div className="flex gap-x-3 text-[10px] font-bold text-stone-500">
                    {readerContext.canonical_series.highest_rating != null && (
                      <span>High {readerContext.canonical_series.highest_rating.toFixed(1)}</span>
                    )}
                    {readerContext.canonical_series.lowest_rating != null && (
                      <span>Low {readerContext.canonical_series.lowest_rating.toFixed(1)}</span>
                    )}
                  </div>
                </>
              )}
            </section>
          ) : null}

          {readerContext.crossover_panel.length > 0 ? (
            <section aria-labelledby="crossovers-heading" className="rounded-2xl border border-white/10 bg-white/[0.04] p-3 space-y-3">
              <h3 id="crossovers-heading" className="text-[10px] font-black uppercase tracking-[0.18em] text-stone-500">
                Crossovers
              </h3>
              <ul className="space-y-2" aria-label="Crossover memberships">
                {readerContext.crossover_panel.map((crossover) => (
                  <li key={crossover.group_id} className="rounded-xl border border-white/10 bg-black/20 p-2.5 space-y-1.5">
                    <div className="flex items-center justify-between gap-2">
                      <p className="truncate text-xs font-black text-stone-200">{crossover.group_name}</p>
                      <span className="shrink-0 text-[10px] font-bold text-stone-500">
                        {crossover.read_count}/{crossover.node_count} read
                      </span>
                    </div>
                    <div className="flex items-baseline gap-x-2">
                      <span className="text-sm font-black text-stone-100">
                        {crossover.average_rating != null ? crossover.average_rating.toFixed(2) : '—'}
                      </span>
                      <span className="text-[10px] font-bold text-stone-500">
                        {crossover.rated_count} rated
                      </span>
                    </div>
                    <ul className="mt-1 flex flex-wrap gap-1">
                      {crossover.nodes.map((node) => (
                        <li
                          key={node.node_id}
                          className={`rounded-full border px-2 py-0.5 text-[9px] font-bold ${
                            node.is_read
                              ? 'border-amber-700/40 bg-amber-900/15 text-amber-300'
                              : 'border-white/10 bg-white/5 text-stone-400'
                          }`}
                          title={node.thread_title ?? `Issue ${node.issue_number}`}
                        >
                          {node.thread_title ?? (node.issue_number ? `#${node.issue_number}` : '—')}
                        </li>
                      ))}
                    </ul>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
        </>
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

      <section aria-labelledby="rating-heading" className="space-y-3 rounded-2xl border border-white/10 bg-black/10 p-3">
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
          {rating >= RATING_THRESHOLD
            ? 'Moves this thread to the front of the queue.'
            : 'Moves this thread beyond the next roll range.'}
        </p>
      </section>

      {activeRatingThread?.issues_remaining === 1 ? (
        <div className="rounded-xl border border-amber-600/20 bg-amber-600/10 p-3 text-center">
          <p className="text-[10px] font-black uppercase tracking-[0.15em] text-amber-500">
            This is the last issue in the thread
          </p>
        </div>
      ) : null}

      <div
        className="rating-actions sticky bottom-0 -mx-3 space-y-2 border-t border-white/10 bg-[#1a1410]/95 px-3 pt-3 pb-[calc(env(safe-area-inset-bottom)+5.5rem)] backdrop-blur md:static md:-mx-4 md:px-4 md:pb-3"
        data-testid="rating-actions"
      >
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
          {rateIsPending ? 'Saving…' : issuesRemaining === 1 ? 'Mark read & complete' : 'Mark read & save'}
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
            className="min-h-11 rounded-xl border border-white/10 bg-white/5 px-4 py-3 text-xs font-black uppercase tracking-[0.15em] text-stone-400 transition hover:bg-white/10 focus:ring-2 focus:ring-amber-500 disabled:opacity-50"
          >
            Cancel roll
          </button>
        </div>
      </div>

      <ComicVineIssueCard issueId={issueId} />

      <ReadingRouteExplanation
        isOpen={isRouteExplanationOpen}
        issueId={issueId}
        issueLabel={`${threadTitle}${issueNumber != null ? ` #${issueNumber}` : ''}`}
        readingOrders={readingOrders}
        connectedThreads={connectedThreads}
        onClose={() => setIsRouteExplanationOpen(false)}
      />

      {activeRatingThread ? (
        <IssueCorrectionDialog
          isOpen={isCorrectionDialogOpen}
          threadId={activeRatingThread.id}
          currentIssueNumber={activeRatingThread.next_issue_number ?? activeRatingThread.issue_number}
          totalIssues={activeRatingThread.total_issues}
          threadTitle={activeRatingThread.title}
          onClose={() => setIsCorrectionDialogOpen(false)}
          onSuccess={() => {
            setIsCorrectionDialogOpen(false)
            onRefreshThread()
          }}
        />
      ) : null}

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
