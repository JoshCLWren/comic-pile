import { useEffect, useState } from 'react'
import {
  comicVineApi,
  type ComicVineIssueIntelligence,
  type ComicVineRelatedIssue,
} from '../../../services/api'

interface ComicVineIssueCardProps {
  issueId: number | null | undefined
}

function formatDate(value: string | null): string | null {
  if (!value) return null
  const [year, month, day] = value.split('-').map(Number)
  if (!year || !month || !day) return value
  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    timeZone: 'UTC',
  }).format(new Date(Date.UTC(year, month - 1, day)))
}

function relatedLabel(issue: ComicVineRelatedIssue): string {
  const identity = [issue.series_name, issue.issue_number ? `#${issue.issue_number}` : null]
    .filter(Boolean)
    .join(' ')
  return identity || issue.name || `ComicVine issue ${issue.comicvine_issue_id}`
}

export function ComicVineIssueCard({ issueId }: ComicVineIssueCardProps) {
  const [metadata, setMetadata] = useState<ComicVineIssueIntelligence | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [imageFailed, setImageFailed] = useState(false)

  useEffect(() => {
    let active = true
    setMetadata(null)
    setImageFailed(false)
    if (!issueId) return () => { active = false }

    setIsLoading(true)
    comicVineApi.getIssueIntelligence(issueId)
      .then((result) => {
        if (active) setMetadata(result)
      })
      .catch(() => {
        if (active) setMetadata(null)
      })
      .finally(() => {
        if (active) setIsLoading(false)
      })

    return () => { active = false }
  }, [issueId])

  if (!issueId || (!isLoading && !metadata)) return null
  if (isLoading) {
    return <div className="h-16 rounded-xl bg-white/5 animate-pulse" aria-label="Loading comic details" />
  }
  if (!metadata) return null

  const date = formatDate(metadata.store_date) ?? formatDate(metadata.cover_date)
  return (
    <details className="group bg-white/5 border border-white/10 rounded-2xl overflow-hidden text-left">
      <summary className="min-h-16 p-3 flex items-center gap-3 cursor-pointer list-none focus:ring-2 focus:ring-amber-500">
        {metadata.image_url && !imageFailed && (
          <img
            src={metadata.image_url}
            alt=""
            loading="lazy"
            className="w-11 h-16 object-cover rounded-md bg-stone-900 shrink-0"
            onError={() => setImageFailed(true)}
          />
        )}
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-[10px] font-black uppercase tracking-[0.18em] text-amber-500">Comic details</span>
            {metadata.story_arcs.length > 0 && (
              <span className="px-2 py-0.5 rounded-full bg-blue-900/30 text-[9px] font-bold text-blue-300">
                {metadata.story_arcs.length} {metadata.story_arcs.length === 1 ? 'story arc' : 'story arcs'}
              </span>
            )}
          </div>
          <p className="text-sm font-bold text-stone-200 truncate">
            {metadata.series_name ?? 'ComicVine'}{metadata.issue_number ? ` #${metadata.issue_number}` : ''}
          </p>
          <p className="text-[10px] text-stone-500 truncate">
            {[metadata.name, date].filter(Boolean).join(' · ')}
          </p>
        </div>
        <span className="text-stone-500 group-open:rotate-180 transition-transform" aria-hidden="true">⌄</span>
      </summary>

      <div className="px-3 pb-4 border-t border-white/10 space-y-4">
        {metadata.description && (
          <p className="pt-3 text-xs leading-relaxed text-stone-300">{metadata.description}</p>
        )}

        {metadata.creators.length > 0 && (
          <section>
            <h3 className="text-[10px] font-black uppercase tracking-wider text-stone-500 mb-1">Creators</h3>
            <div className="space-y-1">
              {metadata.creators.map((creator, index) => (
                <p key={`${creator.name}-${index}`} className="text-xs text-stone-300">
                  <span className="font-bold">{creator.name}</span>
                  {creator.roles.length > 0 && <span className="text-stone-500"> · {creator.roles.join(', ')}</span>}
                </p>
              ))}
            </div>
          </section>
        )}

        {metadata.story_arcs.map((arc) => (
          <section key={arc.comicvine_arc_id}>
            <div className="flex items-center justify-between gap-2 mb-2">
              <h3 className="text-xs font-black text-blue-300">{arc.name}</h3>
              <span className="text-[9px] text-stone-500 shrink-0">
                {arc.related_issues.filter((issue) => issue.comicpile_matches.length > 0).length} in ComicPile ·{' '}
                {arc.related_issues.filter((issue) => issue.comicpile_matches.length === 0).length} missing
              </span>
            </div>
            <p className="text-[9px] text-stone-500 mb-2">Related by story-arc membership, not reading order.</p>
            <div className="space-y-1.5 max-h-64 overflow-y-auto overscroll-contain">
              {arc.related_issues.map((issue) => (
                <div key={issue.comicvine_issue_id} className="p-2 rounded-lg bg-black/15 border border-white/5">
                  <div className="flex gap-2 justify-between">
                    <span className="text-[11px] font-bold text-stone-300">{relatedLabel(issue)}</span>
                    {issue.comicpile_matches.length === 0 ? (
                      <span className="text-[9px] text-amber-500 shrink-0">Missing</span>
                    ) : (
                      <span className="text-[9px] text-teal-400 shrink-0">
                        {issue.comicpile_matches.some((match) => match.status === 'unread') ? 'Unread' : 'Read'}
                      </span>
                    )}
                  </div>
                  {issue.comicpile_matches.map((match) => (
                    <p key={match.issue_id} className="text-[9px] text-stone-500">
                      {match.thread_title} #{match.issue_number} · {match.status}
                    </p>
                  ))}
                </div>
              ))}
            </div>
          </section>
        ))}

        {metadata.comicvine_url && (
          <a
            href={metadata.comicvine_url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex min-h-11 items-center text-xs font-bold text-amber-500 hover:text-amber-400"
          >
            View source on ComicVine
          </a>
        )}
      </div>
    </details>
  )
}
