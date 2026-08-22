import { useState, useRef, useEffect } from 'react'
import { useComicVineIssueIntelligence } from '../../../hooks/useComicVineIssueIntelligence'
import { type ComicVineRelatedIssue } from '../../../services/api'
import { extractComicIdentity, getMemberState, getStateLabel, getStateColorClass, normalizeArcName } from '../../../utils/comicIdentity'
import AddToComicPileDialog from '../../../components/AddToComicPileDialog'

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
    if (storyArcsDetailsRef.current) {
      storyArcsDetailsRef.current.open = true
    }
  }, [metadata])

  const [addDialogOpen, setAddDialogOpen] = useState(false)
  const [addDialogData, setAddDialogData] = useState<{
    seriesName: string | null
    issueNumber: string | null
    comicvineIssueId: string
    imageUrl: string | null
  } | null>(null)

  const handleAddToComicPile = (identity: { primary: string; secondary: string | null }, comicvineIssueId: string, seriesName: string | null, issueNumber: string | null, imageUrl: string | null) => {
    setAddDialogData({ seriesName, issueNumber, comicvineIssueId, imageUrl })
    setAddDialogOpen(true)
  }

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
    <>
    <section
      aria-labelledby={metadata.name ? 'comic-identity-heading' : undefined}
      aria-label={metadata.name ? undefined : 'Comic details'}
      className="w-full space-y-4"
    >
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
              <span className="ml-auto text-stone-500 group-open:rotate-180 transition-transform" aria-hidden="true">⌄</span>
            </summary>
            <div id="creators-list" className="pl-6 pr-2 pb-2 space-y-1 border-l border-white/10">
              {creatorsToShow.map((creator, index) => (
                <p key={`${creator.name}-${index}`} className="text-xs text-stone-300">
                  <span className="font-bold">{creator.name}</span>
                  {creator.roles.length > 0 && <span className="text-stone-500"> · {creator.roles.join(', ')}</span>}
                </p>
              ))}
            </div>
            {hasMoreCreators && (
              <button
                type="button"
                onClick={() => setShowAllCreators(!showAllCreators)}
                className="ml-6 text-[10px] font-bold text-amber-500 hover:text-amber-400 py-1"
                aria-expanded={showAllCreators}
                aria-controls="creators-list"
              >
                {showAllCreators ? 'Show less' : `Show all ${metadata.creators.length}`}
              </button>
            )}
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
                .map((arc) => {
                  const isExpanded = showAllRelatedIssues[arc.comicvine_arc_id]
                  const displayedIssues = isExpanded ? arc.related_issues : arc.related_issues.slice(0, RELATED_ISSUES_PER_ARC_LIMIT)
                  const hasMore = arc.related_issues.length > RELATED_ISSUES_PER_ARC_LIMIT

                  return (
                    <section key={arc.comicvine_arc_id} className="space-y-2">
                      <h3 className="text-xs font-bold text-blue-300">{normalizeArcName(arc.name)}</h3>
                      <p className="text-[9px] text-stone-500">
                        {arc.related_issues.filter((issue) => issue.comicpile_matches.length > 0).length} in ComicPile ·{' '}
                        {arc.related_issues.filter((issue) => issue.comicpile_matches.length === 0).length} missing
                        {arc.total_related_count != null && arc.total_related_count > arc.related_issues.length && (
                          <span className="ml-1 text-stone-600">({arc.related_issues.length} of {arc.total_related_count} shown)</span>
                        )}
                      </p>
                      <p className="text-[9px] text-stone-500">Related by story-arc membership, not reading order.</p>
                      <div className="space-y-1.5 max-h-48 overflow-y-auto overscroll-contain">
                        {displayedIssues.map((issue) => {
                          const identity = extractComicIdentity(issue)
                          const state = getMemberState(issue)
                          const stateLabel = getStateLabel(state)
                          const stateColorClass = getStateColorClass(state)

                          return (
                            <div key={issue.comicvine_issue_id} className="p-2 rounded-lg bg-black/15 border border-white/5">
                              <div className="flex gap-2 justify-between items-start">
                                <div className="flex-1 min-w-0">
                                  <span className="text-[11px] font-bold text-stone-300 truncate block">{identity.primary}</span>
                                  {identity.secondary && (
                                    <span className="text-[10px] text-stone-500 truncate block">{identity.secondary}</span>
                                  )}
                                </div>
                                <div className="flex items-center gap-2 shrink-0">
                                  <span
                                    className={`text-[9px] font-bold shrink-0 ${stateColorClass}`}
                                    aria-label={`Status: ${stateLabel}`}
                                  >
                                    {stateLabel}
                                  </span>
                                  {state === 'missing' && (
                                    <button
                                      type="button"
                                      onClick={() => handleAddToComicPile(identity, issue.comicvine_issue_id, issue.series_name, issue.issue_number, null)}
                                      className="text-[9px] font-bold text-amber-500 hover:text-amber-400 shrink-0 px-2 py-0.5 rounded border border-amber-500/30 bg-amber-500/10 transition-colors"
                                      aria-label={`Add ${identity.primary} to ComicPile`}
                                    >
                                      Add to ComicPile
                                    </button>
                                  )}
                                </div>
                              </div>
                              {issue.comicpile_matches.map((match) => (
                                <p key={match.issue_id} className="text-[9px] text-stone-500 mt-1">
                                  {match.thread_title} #{match.issue_number} · {match.status}
                                </p>
                              ))}
                            </div>
                          )
                        })}
                        {hasMore && (
                          <button
                            type="button"
                            onClick={() => setShowAllRelatedIssues((prev) => ({ ...prev, [arc.comicvine_arc_id]: !prev[arc.comicvine_arc_id] }))}
                            className="w-full text-left text-[10px] font-bold text-amber-500 hover:text-amber-400 py-1"
                            aria-expanded={isExpanded}
                          >
                            {isExpanded ? 'Show fewer' : `Show all ${arc.related_issues.length} issues`}
                          </button>
                        )}
                      </div>
                    {arc.comicvine_url && (
                      <a
                        href={arc.comicvine_url}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex min-h-8 items-center text-xs font-bold text-blue-400 hover:text-blue-300 mt-2"
                      >
                        View story arc on ComicVine
                      </a>
                    )}
                    </section>
                  )
                })}
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
            View issue on ComicVine
          </a>
        )}
      </div>
    </section>
    {addDialogData && (
      <AddToComicPileDialog
        isOpen={addDialogOpen}
        seriesName={addDialogData.seriesName}
        issueNumber={addDialogData.issueNumber}
        comicvineIssueId={addDialogData.comicvineIssueId}
        imageUrl={addDialogData.imageUrl}
        onClose={() => setAddDialogOpen(false)}
        onAdded={() => setAddDialogOpen(false)}
      />
    )}
    </>
  )
}
