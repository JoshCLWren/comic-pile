import { PillarHeader } from './PillarHeader'
import { ContinuityReadinessSummary } from './ContinuityReadinessSummary'
import { ComicVineIssueCard } from './ComicVineIssueCard'
import { getProgressPercentage } from '../utils'
import type { RatingThread } from '../types'

const ACCENT = 'var(--comic-accent, #d4890e)'

interface ComicPillarProps {
  activeRatingThread: RatingThread | null
  currentDie: number
  rolledResult: number | null
  hasValidRolledResult: boolean
  poolSize: number
  copyStatus: 'idle' | 'copied' | 'failed'
  onCopy: () => void
  onEditIssue: () => void
}

export function ComicPillar({
  activeRatingThread,
  currentDie,
  rolledResult,
  hasValidRolledResult,
  poolSize,
  copyStatus,
  onCopy,
  onEditIssue,
}: ComicPillarProps) {
  const threadTitle = activeRatingThread?.title ?? 'Loading…'
  const issueNumber = activeRatingThread?.next_issue_number ?? activeRatingThread?.issue_number ?? null
  const issueId = activeRatingThread?.issue_id ?? activeRatingThread?.next_issue_id
  const totalIssues = activeRatingThread?.total_issues ?? null
  const issuesRemaining = activeRatingThread?.issues_remaining ?? 0
  const progress = getProgressPercentage(activeRatingThread)

  return (
    <div className="space-y-3 rounded-2xl border border-white/10 bg-white/[0.04] p-3 md:p-4">
      <PillarHeader number="01" title="The Comic" accentColor={ACCENT} />

      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[10px] font-black uppercase tracking-[0.18em] text-stone-500">
            Selected issue
          </p>
          <h2 className="mt-1 text-xl font-black leading-tight text-stone-100">
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
              onClick={onCopy}
              disabled={!activeRatingThread?.title}
              className="min-h-11 rounded-xl border border-white/10 bg-white/5 px-3 text-[10px] font-black uppercase tracking-wider text-stone-300 transition hover:bg-white/10 focus:ring-2 focus:ring-amber-500 disabled:opacity-30"
              aria-label={`Copy ${threadTitle} ${issueNumber}`}
            >
              {copyStatus === 'copied' ? 'Copied' : copyStatus === 'failed' ? 'Retry copy' : 'Copy'}
            </button>
            <button
              type="button"
              onClick={onEditIssue}
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

      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] font-bold text-stone-500">
        {totalIssues && issueNumber != null ? (
          <span>Issue {issueNumber} of {totalIssues}</span>
        ) : null}
        {totalIssues && issueNumber != null ? <span aria-hidden="true">·</span> : null}
        <span>{progress}% complete</span>
        <span aria-hidden="true">·</span>
        <span>{issuesRemaining} left</span>
      </div>

      <ContinuityReadinessSummary issueId={issueId} />

      <ComicVineIssueCard issueId={issueId} />
    </div>
  )
}
