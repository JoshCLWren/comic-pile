import { useState } from 'react'
import type { ComicVineIssueIntelligence } from '../../../services/api'
import { PillarFrame } from './PillarFrame'
import type { RatingThread } from '../types'

interface ComicPillarProps {
  activeRatingThread: RatingThread | null
  comicVineMetadata: ComicVineIssueIntelligence | null
  comicVineIsLoading: boolean
}

export function ComicPillar({
  activeRatingThread,
  comicVineMetadata,
  comicVineIsLoading,
  onEditIssue,
}: ComicPillarProps) {
  const [failedCoverUrl, setFailedCoverUrl] = useState<string | null>(null)

  const threadTitle = activeRatingThread?.title ?? 'Loading…'
  const issueNumber = activeRatingThread?.next_issue_number ?? activeRatingThread?.issue_number ?? null
  const totalIssues = activeRatingThread?.total_issues ?? null
  const issuesRemaining = activeRatingThread?.issues_remaining ?? 0
  const progress = totalIssues && totalIssues > 0
    ? Math.round(((totalIssues - (issuesRemaining || 0)) / totalIssues) * 100)
    : 0
  const format = activeRatingThread?.format ?? ''

  const coverUrl = comicVineMetadata?.image_url && comicVineMetadata.image_url !== failedCoverUrl
    ? comicVineMetadata.image_url
    : null

  return (
    <PillarFrame number="01" title="THE COMIC" accent="comic">
      <div className="flex flex-col items-center gap-3">
        {comicVineIsLoading ? (
          <div
            className="aspect-[2/3] w-full max-w-[160px] rounded-lg bg-white/5 animate-pulse"
            aria-label="Loading cover"
          />
        ) : coverUrl ? (
          <img
            src={coverUrl}
            alt=""
            loading="lazy"
            className="aspect-[2/3] w-full max-w-[160px] object-cover rounded-lg bg-stone-900"
            onError={() => setFailedCoverUrl(comicVineMetadata!.image_url)}
          />
        ) : (
          <div className="flex aspect-[2/3] w-full max-w-[160px] items-center justify-center rounded-lg bg-stone-800">
            <span className="text-[10px] font-bold text-stone-500">No cover</span>
          </div>
        )}

        <div className="text-center">
          <h2 className="text-xl font-black leading-tight" style={{ color: 'var(--theme-text-primary)' }}>
            {threadTitle}
            {issueNumber != null ? <span style={{ color: 'var(--theme-comic-accent)' }}> #{issueNumber}</span> : null}
          </h2>
          {format ? (
            <p className="text-[10px] font-black uppercase tracking-widest" style={{ color: 'var(--theme-text-muted)' }}>
              {format}
            </p>
          ) : null}
        </div>
      </div>

      {totalIssues && issueNumber != null ? (
        <div className="grid grid-cols-2 gap-x-2 gap-y-1 text-[11px]">
          <span style={{ color: 'var(--theme-text-muted)' }}>Issue</span>
          <span style={{ color: 'var(--theme-text-primary)' }}>{issueNumber} of {totalIssues}</span>
          <span style={{ color: 'var(--theme-text-muted)' }}>Progress</span>
          <span style={{ color: 'var(--theme-text-primary)' }}>{progress}% complete</span>
          <span style={{ color: 'var(--theme-text-muted)' }}>Remaining</span>
          <span style={{ color: 'var(--theme-text-primary)' }}>{issuesRemaining} left</span>
        </div>
      ) : (
        <div className="text-[11px]" style={{ color: 'var(--theme-text-muted)' }}>
          {issuesRemaining} left
        </div>
      )}

      {comicVineMetadata?.description ? (
        <p className="text-xs leading-relaxed" style={{ color: 'var(--theme-text-muted)' }}>
          {comicVineMetadata.description}
        </p>
      ) : null}

      {comicVineMetadata && comicVineMetadata.story_arcs.length > 0 ? (
        <div className="flex flex-wrap gap-1">
          {comicVineMetadata.story_arcs.map((arc) => (
            <span
              key={arc.comicvine_arc_id}
              className="rounded-full px-2 py-0.5 text-[9px] font-bold"
              style={{
                backgroundColor: 'rgba(167, 139, 250, 0.2)',
                color: 'var(--theme-personal-accent)',
              }}
            >
              {arc.name}
            </span>
          ))}
        </div>
      ) : null}
    </PillarFrame>
  )
}
