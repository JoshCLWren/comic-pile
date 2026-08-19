import { useState, useRef, useEffect } from 'react'
import { useComicVineIssueIntelligence } from '../../../hooks/useComicVineIssueIntelligence'
import { type ComicVineRelatedIssue } from '../../../services/api'

interface ComicIdentityProps {
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
  if (!identity) return issue.name || `ComicVine issue ${issue.comicvine_issue_id}`
  return issue.name ? `${identity} - ${issue.name}` : identity
}

const CREATOR_LIMIT = 6
const STORY_ARC_LIMIT = 3
const RELATED_ISSUES_PER_ARC_LIMIT = 5

export function ComicIdentity({ issueId }: ComicIdentityProps) {
  const { metadata, isLoading } = useComicVineIssueIntelligence(issueId)
  const [failedImageUrl, setFailedImageUrl] = useState<string | null>(null)
  const [showAllCreators, setShowAllCreators] = useState(false)
  const [showAllStoryArcs, setShowAllStoryArcs] = useState(false)
  const [showAllRelatedIssues, setShowAllRelatedIssues] = useState<Record<number, boolean>>({})
  const creatorsDetailsRef = useRef<HTMLDetailsElement>(null)
  const storyArcsDetailsRef = useRef<HTMLDetailsElement>(null)

  useEffect(() => {
    if (creatorsDetailsRef.current) {
      creatorsDetailsRef.current.open = true
    }
  }, [])

  useEffect(() => {
    if (storyArcsDetailsRef.current) {
      storyArcsDetailsRef.current.open = true
    }
  }, [])

  if (!issueId || (!isLoading && !metadata)) return null
  if (isLoading) {
    return (
      <div className="w-full aspect-[2/3] rounded-xl bg-white/5 animate-pulse" aria-label="Loading comic details" />
    )
  }
  if (!metadata) return null

  const date = formatDate(metadata.store_date) ?? formatDate(metadata.cover_date)
  const creatorsToShow = showAllCreators ? metadata.creators : metadata.creators.slice(0, CREATOR_LIMIT)
  const hasMoreCreators = metadata.creators.length > CREATOR_LIMIT

  return (
    <section aria-labelledby="comic-identity-heading" className="w-full space-y-4">
      <div className="relative aspect-[2/3] w-full max-w-full rounded-xl overflow-hidden bg-stone-900" style={{ border: '1px solid var(--theme-border)' }}>
        {metadata.image_url && metadata.image_url !== failedImageUrl ? (
          <img
            src={metadata.image_url}
            alt=""
            loading="eager"
            className="w-full h-full object-cover"
            onError={() => setFailedImageUrl(metadata.image_url)}
          />
        ) : (
          <div data-testid="cover-placeholder" className="w-full h-full flex items-center justify-center text-stone-600" aria-hidden="true">
            <svg className="w-16 h-16" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 002 2z" />
            </svg>
          </div>
        )}
      </div>

      <div className="space-y-3">
        <div className="flex flex-col gap-1">
          <p className="text-[10px] font-black uppercase tracking-[0.18em]" style={{ color: 'var(--theme-comic-accent)' }}>
            {metadata.series_name ?? 'ComicVine'}{metadata.issue_number ? ` #${metadata.issue_number}` : ''}
          </p>
          {metadata.name && (
            <h2 id="comic-identity-heading" className="text-lg font-bold text-stone-100 leading-tight">
              {metadata.name}
            </h2>
          )}
          {date && (
            <p className="text-[11px] text-stone-500">{date}</p>
          )}
        </div>

        {metadata.description && (
          <details className="group space-y-2">
            <summary className="flex items-center gap-2 cursor-pointer list-none focus:ring-2 focus:ring-amber-500 rounded-lg p-2 hover:bg-white/5 transition-colors">
              <span className="text-[10px] font-black uppercase tracking-wider text-stone-400">Summary</span>
              <span className="text-stone-500 group-open:rotate-180 transition-transform" aria-hidden="true">⌄</span>
            </summary>
            <div className="pl-6 pr-2 pb-2 text-xs leading-relaxed text-stone-300 border-l border-white/10">
              {metadata.description}
            </div>
          </details>
        )}

        {metadata.creators.length > 0 && (
          <details ref={creatorsDetailsRef} className="group space-y-2">
            <summary className="flex items-center gap-2 cursor-pointer list-none focus:ring-2 focus:ring-amber-500 rounded-lg p-2 hover:bg-white/5 transition-colors">
              <span className="text-[10px] font-black uppercase tracking-wider text-stone-400">Creators</span>
              {hasMoreCreators && (
                <button
                  type="button"
                  onClick={() => setShowAllCreators(!showAllCreators)}
                  className="ml-auto text-[10px] font-bold text-amber-500 hover:text-amber-400"
                  aria-expanded={showAllCreators}
                  aria-controls="creators-list"
                >
                  {showAllCreators ? 'Show less' : `Show all ${metadata.creators.length}`}
                </button>
              )}
            </summary>
            <div id="creators-list" className="pl-6 pr-2 pb-2 space-y-1 border-l border-white/10">
              {creatorsToShow.map((creator, index) => (
                <p key={`${creator.name}-${index}`} className="text-xs text-stone-300">
                  <span className="font-bold">{creator.name}</span>
                  {creator.roles.length > 0 && <span className="text-stone-500"> · {creator.roles.join(', ')}</span>}
                </p>
              ))}
            </div>
          </details>
        )}

        {metadata.story_arcs.length > 0 && (
          <details ref={storyArcsDetailsRef} className="group space-y-3">
            <summary className="flex items-center gap-2 cursor-pointer list-none focus:ring-2 focus:ring-amber-500 rounded-lg p-2 hover:bg-white/5 transition-colors">
              <span className="text-[10px] font-black uppercase tracking-wider text-stone-400">
                Story arcs ({metadata.story_arcs.length})
              </span>
            </summary>
            <div className="pl-6 pr-2 pb-2 space-y-3 border-l border-white/10">
              {metadata.story_arcs
                .slice(0, showAllStoryArcs ? metadata.story_arcs.length : STORY_ARC_LIMIT)
                .map((arc) => (
                  <section key={arc.comicvine_arc_id} className="space-y-2">
                    <h3 className="text-xs font-bold text-blue-300">{arc.name}</h3>
                    <p className="text-[9px] text-stone-500">
                      {arc.related_issues.filter((issue) => issue.comicpile_matches.length > 0).length} in ComicPile ·{' '}
                      {arc.related_issues.filter((issue) => issue.comicpile_matches.length === 0).length} missing
                    </p>
                    <div className="space-y-1.5 max-h-48 overflow-y-auto overscroll-contain">
                      {arc.related_issues
                        .slice(0, showAllRelatedIssues[arc.comicvine_arc_id] ? arc.related_issues.length : RELATED_ISSUES_PER_ARC_LIMIT)
                        .map((issue) => (
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
                      {arc.related_issues.length > RELATED_ISSUES_PER_ARC_LIMIT && (
                        <button
                          type="button"
                          onClick={() => setShowAllRelatedIssues((prev) => ({ ...prev, [arc.comicvine_arc_id]: !prev[arc.comicvine_arc_id] }))}
                          className="w-full text-left text-[10px] font-bold text-amber-500 hover:text-amber-400 py-1"
                          aria-expanded={showAllRelatedIssues[arc.comicvine_arc_id] || false}
                        >
                          {showAllRelatedIssues[arc.comicvine_arc_id] ? 'Show fewer' : `Show all ${arc.related_issues.length} issues`}
                        </button>
                      )}
                    </div>
                  </section>
                ))}
              {metadata.story_arcs.length > STORY_ARC_LIMIT && (
                <button
                  type="button"
                  onClick={() => setShowAllStoryArcs(!showAllStoryArcs)}
                  className="w-full text-left text-[10px] font-bold text-amber-500 hover:text-amber-400 py-1"
                  aria-expanded={showAllStoryArcs}
                >
                  {showAllStoryArcs ? 'Show fewer arcs' : `Show all ${metadata.story_arcs.length} story arcs`}
                </button>
              )}
            </div>
          </details>
        )}

        {metadata.comicvine_url && (
          <a
            href={metadata.comicvine_url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex min-h-11 items-center text-xs font-bold text-amber-500 hover:text-amber-400 focus:ring-2 focus:ring-amber-500 rounded-lg px-2"
          >
            View source on ComicVine
          </a>
        )}
      </div>
    </section>
  )
}