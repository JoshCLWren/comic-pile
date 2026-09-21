import { useEffect, useRef, useState, type CSSProperties, useMemo } from 'react'
import { useComicVineIssueIntelligence } from '../../../hooks/useComicVineIssueIntelligence'
import { canonicalCreatorKey, useCreatorSummaries } from '../../../hooks/useCreatorSummaries'
import { type ComicVineRelatedIssue } from '../../../services/api'
import { extractComicIdentity, getMemberState, getStateLabel, getStateColorClass, normalizeArcName, computeArcNeighborAnchors } from '../../../utils/comicIdentity'
import AddToComicPileDialog from '../../../components/AddToComicPileDialog'
import ImageWithLoading from '../../../components/ImageWithLoading'
import { CreatorName } from './CreatorName'
import { optimizedImageSrcSet, optimizedImageUrl } from '../../../services/imageDelivery'

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
const COVER_HEIGHT_CAP_VH = 45
const COVER_RATIO_FALLBACK = 2 / 3

function formatRating(value: number): string {
  const normalized = parseFloat(value.toFixed(2))
  return Number.isFinite(normalized) ? String(normalized) : String(value)
}

export function ComicIdentity({ issueId }: ComicIdentityProps) {
  const { metadata, isLoading, refetch } = useComicVineIssueIntelligence(issueId)
  const [failedImageUrl, setFailedImageUrl] = useState<string | null>(null)
  const [coverRatio, setCoverRatio] = useState<number | null>(null)
  const [showAllCreators, setShowAllCreators] = useState(false)
  const [showAllStoryArcs, setShowAllStoryArcs] = useState(false)
  const [showAllRelatedIssues, setShowAllRelatedIssues] = useState<Record<number, boolean>>({})
  const creatorsDetailsRef = useRef<HTMLDetailsElement>(null)
  const storyArcsDetailsRef = useRef<HTMLDetailsElement>(null)

  useEffect(() => {
    setCoverRatio(null)
  }, [metadata?.image_url, isLoading])

  useEffect(() => {
    if (creatorsDetailsRef.current) {
      creatorsDetailsRef.current.open = true
    }
    if (storyArcsDetailsRef.current) {
      storyArcsDetailsRef.current.open = true
    }
  }, [metadata])

  const coverAspectRatio = coverRatio ?? COVER_RATIO_FALLBACK
  const coverWidthCapVh = COVER_HEIGHT_CAP_VH * coverAspectRatio
  const coverStyle: CSSProperties = {
    aspectRatio: `${coverAspectRatio}`,
    width: `min(100%, calc(${coverWidthCapVh}vh))`,
  }
  const coverFrameBorder = { border: '1px solid var(--theme-border)' }

  const [addDialogOpen, setAddDialogOpen] = useState(false)
  const [addDialogData, setAddDialogData] = useState<{
    seriesName: string | null
    issueNumber: string | null
    comicvineIssueId: string
    imageUrl: string | null
    anchorBeforeThreadId: number | null
    anchorAfterThreadId: number | null
  } | null>(null)

  const handleAddToComicPile = (
    identity: { primary: string; secondary: string | null },
    issue: ComicVineRelatedIssue,
    relatedIssues: ComicVineRelatedIssue[],
    imageUrl: string | null,
  ) => {
    const missingIndex = relatedIssues.findIndex(
      (candidate) => candidate.comicvine_issue_id === issue.comicvine_issue_id,
    )
    const { anchorBeforeThreadId, anchorAfterThreadId } = computeArcNeighborAnchors(
      relatedIssues,
      missingIndex,
    )
    setAddDialogData({
      seriesName: issue.series_name,
      issueNumber: issue.issue_number,
      comicvineIssueId: issue.comicvine_issue_id,
      imageUrl,
      anchorBeforeThreadId,
      anchorAfterThreadId,
    })
    setAddDialogOpen(true)
  }

  const creatorKeys = useMemo(() => {
    if (!metadata) return [] as string[]
    const seen = new Set<string>()
    const keys: string[] = []
    for (const creator of metadata.creators) {
      if (creator.creator_id == null) continue
      const key = canonicalCreatorKey(creator.creator_id)
      if (!seen.has(key)) {
        seen.add(key)
        keys.push(key)
      }
    }
    return keys
  }, [metadata])

  const { data: creatorSummaries } = useCreatorSummaries(
    creatorKeys.length > 0 ? creatorKeys : undefined,
  )
  const summaries = creatorSummaries?.summaries ?? {}
  const coverage = creatorSummaries?.coverage ?? null

  if (!issueId || (!isLoading && !metadata)) return null
  if (isLoading) {
    return (
      <div
        data-testid="comic-cover"
        data-cover-aspect-ratio={coverAspectRatio}
        data-cover-height-cap-vh={COVER_HEIGHT_CAP_VH}
        data-cover-width-cap-vh={coverWidthCapVh}
        aria-label="Loading comic details"
        className="relative mx-auto overflow-hidden rounded-xl bg-white/5 animate-pulse"
        style={{ ...coverStyle, ...coverFrameBorder }}
      />
    )
  }
  if (!metadata) return null

  const date = formatDate(metadata.store_date) ?? formatDate(metadata.cover_date)
  const creatorsToShow = showAllCreators ? metadata.creators : metadata.creators.slice(0, CREATOR_LIMIT)
  const hasMoreCreators = metadata.creators.length > CREATOR_LIMIT

  return (
    <>
    <section
      aria-label={metadata.name || 'Comic details'}
      className="w-full space-y-4"
    >
      <div
        data-testid="comic-cover"
        data-cover-aspect-ratio={coverAspectRatio}
        data-cover-height-cap-vh={COVER_HEIGHT_CAP_VH}
        data-cover-width-cap-vh={coverWidthCapVh}
        className="relative mx-auto overflow-hidden rounded-xl bg-white/5"
        style={{ ...coverStyle, ...coverFrameBorder }}
      >
        {metadata.image_url && metadata.image_url !== failedImageUrl ? (
          <ImageWithLoading
            src={optimizedImageUrl(metadata.image_url, 720) ?? metadata.image_url}
            srcSet={optimizedImageSrcSet(metadata.image_url, [240, 480, 720]) ?? undefined}
            sizes="(min-width: 1024px) 30vh, calc((45vh * 2) / 3)"
            alt=""
            loading="eager"
            className="h-full w-full object-contain"
            placeholderClassName="animate-pulse bg-white/10"
            onLoad={(img) => {
              const { naturalWidth, naturalHeight } = img
              if (naturalWidth > 0 && naturalHeight > 0) {
                setCoverRatio(naturalWidth / naturalHeight)
              }
            }}
            onError={() => setFailedImageUrl(metadata.image_url)}
          />
        ) : (
          <div data-testid="cover-placeholder" className="w-full h-full flex items-center justify-center text-stone-600 flex-col gap-2" aria-hidden="true">
            <svg className="w-16 h-16" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 002 2z" />
            </svg>
            <span className="text-[10px] font-black uppercase tracking-[0.18em] text-stone-500">COMIC COVER</span>
          </div>
        )}
      </div>

      <div className="space-y-3">
        {date && (
          <p className="text-[11px] text-stone-500">{date}</p>
        )}

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
              {creatorsToShow.map((creator, index) => {
                const stableKey = creator.creator_id != null ? canonicalCreatorKey(creator.creator_id) : null
                const summary = stableKey ? summaries[stableKey] : undefined
                const hasRatedStats = summary != null
                const upcomingVisible =
                  summary != null &&
                  coverage != null &&
                  (coverage.upcoming_complete || summary.upcoming_count > 0)
                return (
                  <p
                    key={`${creator.name}-${index}`}
                    data-testid="creator-row"
                    className="flex flex-wrap items-baseline gap-x-1.5 gap-y-0.5 text-xs text-stone-300 min-w-0 break-words"
                  >
                    <span className="font-bold break-words min-w-0">{creator.name}</span>
                    {creator.roles.length > 0 && (
                      <span className="text-stone-500 break-words min-w-0">· {creator.roles.join(', ')}</span>
                    )}
                    {hasRatedStats ? (
                      summary.average_rating != null ? (
                        <>
                          <span className="text-stone-500" aria-hidden="true">
                            ·
                          </span>
                          <span
                            className="inline-flex items-center gap-0.5"
                            aria-label={`Average rating ${formatRating(summary.average_rating)} out of 5 from ${summary.ratings_count} ${summary.ratings_count === 1 ? 'rating' : 'ratings'}${coverage && !coverage.ratings_complete ? ', partial coverage' : ''}`}
                          >
                            <span aria-hidden="true" className="text-amber-400/90">
                              ★
                            </span>
                            <span>{formatRating(summary.average_rating)}</span>
                          </span>
                          <span className="text-stone-500" aria-hidden="true">
                            ·
                          </span>
                          <span
                            aria-label={
                              coverage && !coverage.ratings_complete
                                ? `${summary.ratings_count} rated, partial coverage — lower bound`
                                : `${summary.ratings_count} rated`
                            }
                          >
                            {summary.ratings_count}
                            {coverage && !coverage.ratings_complete && summary.ratings_count > 0 ? '+' : ''} rated
                          </span>
                          {coverage && !coverage.ratings_complete && summary.ratings_count > 0 && (
                            <span className="sr-only"> partial coverage</span>
                          )}
                        </>
                      ) : (
                        <>
                          <span className="text-stone-500" aria-hidden="true">
                            ·
                          </span>
                          <span>0 rated</span>
                        </>
                      )
                    ) : null}
                    {upcomingVisible ? (
                      coverage!.upcoming_complete ? (
                        <>
                          <span className="text-stone-500" aria-hidden="true">
                            ·
                          </span>
                          <span>{summary!.upcoming_count} unread</span>
                        </>
                      ) : (
                        <>
                          <span className="text-stone-500" aria-hidden="true">
                            ·
                          </span>
                          <span
                            aria-label={`At least ${summary!.upcoming_count} unread, partial coverage`}
                          >
                            {summary!.upcoming_count}+ unread
                          </span>
                        </>
                      )
                    ) : null}
                  </p>
                )
              })}
            </div>
            {hasMoreCreators && (
              <button
                type="button"
                onClick={() => setShowAllCreators(!showAllCreators)}
                className="ml-6 inline-flex min-h-6 items-center text-[10px] font-bold text-amber-500 hover:text-amber-400 focus:ring-2 focus:ring-amber-500 rounded"
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
                      <div className="space-y-1.5" data-testid="story-arc-issue-list">
                        {displayedIssues.map((issue) => {
                          const identity = extractComicIdentity(issue, issue.comicpile_matches)
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
                                      onClick={() => handleAddToComicPile(identity, issue, arc.related_issues, null)}
                                      className="inline-flex min-h-6 items-center text-[9px] font-bold text-amber-500 hover:text-amber-400 shrink-0 px-2 rounded border border-amber-500/30 bg-amber-500/10 transition-colors focus:ring-2 focus:ring-amber-500"
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
                            className="w-full inline-flex min-h-6 items-center text-left text-[10px] font-bold text-amber-500 hover:text-amber-400 focus:ring-2 focus:ring-amber-500 rounded"
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
                  className="w-full inline-flex min-h-6 items-center text-left text-[10px] font-bold text-amber-500 hover:text-amber-400 focus:ring-2 focus:ring-amber-500 rounded"
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
        anchorBeforeThreadId={addDialogData.anchorBeforeThreadId}
        anchorAfterThreadId={addDialogData.anchorAfterThreadId}
        onClose={() => setAddDialogOpen(false)}
        onAdded={() => {
          setAddDialogOpen(false)
          refetch()
        }}
      />
    )}
    </>
  )
}
