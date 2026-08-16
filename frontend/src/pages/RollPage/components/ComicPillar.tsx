import { ComicVineIssueCard } from './ComicVineIssueCard'
import type { RatingThread } from '../types'

interface ComicPillarProps {
  activeRatingThread: RatingThread | null
  issueId: number | null
}

export function ComicPillar({ activeRatingThread, issueId }: ComicPillarProps) {
  const threadTitle = activeRatingThread?.title ?? 'Loading…'
  const issueNumber = activeRatingThread?.next_issue_number ?? activeRatingThread?.issue_number ?? null
  const totalIssues = activeRatingThread?.total_issues ?? null
  const issuesRemaining = activeRatingThread?.issues_remaining ?? 0
  const progress = totalIssues ? Math.round(((totalIssues - issuesRemaining) / totalIssues) * 100) : 0

  return (
    <section aria-labelledby="comic-heading" className="space-y-4 p-4 md:p-6">
      <div className="flex items-center justify-between gap-2 mb-2">
        <h2 id="comic-heading" className="text-[10px] font-black uppercase tracking-[0.18em] text-amber-500">
          01 THE COMIC
        </h2>
        <span className="text-[9px] font-bold uppercase tracking-wider text-amber-400/50">warm accent</span>
      </div>

      <div className="space-y-4">
        <div className="relative aspect-[2/3] max-w-xs md:max-w-md mx-auto">
          <ComicVineIssueCard issueId={issueId} />
        </div>

        <div className="text-center space-y-1">
          <p className="text-sm font-black text-stone-200">{threadTitle}</p>
          {issueNumber != null && (
            <p className="text-lg font-black text-amber-400">#{issueNumber}</p>
          )}
        </div>

        <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs md:text-sm">
          <div className="text-right text-stone-500 font-bold">Format</div>
          <div className="text-stone-200 font-black">{activeRatingThread?.format ?? '—'}</div>
          <div className="text-right text-stone-500 font-bold">Progress</div>
          <div className="text-stone-200 font-black">{progress}%</div>
          <div className="text-right text-stone-500 font-bold">Issues Left</div>
          <div className="text-stone-200 font-black">{issuesRemaining}</div>
          {totalIssues && (
            <>
              <div className="text-right text-stone-500 font-bold">Total Issues</div>
              <div className="text-stone-200 font-black">{totalIssues}</div>
            </>
          )}
        </div>

        <div className="border-t border-white/10 pt-4 space-y-2">
          <p className="text-[10px] font-bold uppercase tracking-wider text-stone-500">Summary</p>
          <p className="text-xs leading-relaxed text-stone-400">
            {activeRatingThread?.title} issue {issueNumber ?? '—'} continues the story...
          </p>
        </div>

        <button
          type="button"
          className="w-full min-h-11 rounded-xl border border-amber-700/40 bg-amber-900/15 px-4 text-xs font-black uppercase tracking-wider text-amber-200 hover:bg-amber-900/25 transition-colors focus:ring-2 focus:ring-amber-500"
        >
          View on ComicVine
        </button>
      </div>
    </section>
  )
}