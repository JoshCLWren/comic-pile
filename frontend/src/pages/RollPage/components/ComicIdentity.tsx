import { useEffect, useRef, useState, type CSSProperties, useMemo } from 'react'
import { useComicVineIssueIntelligence } from '../../../hooks/useComicVineIssueIntelligence'
import { useComicVineMetadataHydration } from '../../../hooks/useComicVineMetadataHydration'
import ComicVineMetadataStatus from '../../../components/ComicVineMetadataStatus'
import { canonicalCreatorKey, useCreatorSummaries } from '../../../hooks/useCreatorSummaries'
import { type ComicVineRelatedIssue } from '../../../services/api-comicvine'
import { extractComicIdentity, getMemberState, getStateLabel, getStateColorClass, normalizeArcName, computeArcNeighborAnchors } from '../../../utils/comicIdentity'
import AddToComicPileDialog from '../../../components/AddToComicPileDialog'
import { ComicIssueCover } from '../../../components/ComicIssueCard'
import CompactIssueCardTrigger from '../../../components/CompactIssueCardTrigger'
import { useIssueCards, indexIssueCards } from '../../../hooks/useIssueCards'
import ImageWithLoading from '../../../components/ImageWithLoading'
import Modal from '../../../components/Modal'
import { CreatorName } from './CreatorName'
import { useResponsive } from '../../../utils/responsive'

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
const SUMMARY_LONG_THRESHOLD = 280

function formatRating(value: number): string {
  const normalized = parseFloat(value.toFixed(2))
  return Number.isFinite(normalized) ? String(normalized) : String(value)
}

function EyeIcon({ className }: { className?: string }) {
  return (
    <svg className={className ?? 'w-4 h-4'} fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
    </svg>
  )
}

function ArrowTopRightOnSquareIcon({ className }: { className?: string }) {
  return (
    <svg className={className ?? 'w-4 h-4'} fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
    </svg>
  )
}

export function ComicIdentity({ issueId }: ComicIdentityProps) {
  const { metadata, isLoading, isError, error, refetch } = useComicVineIssueIntelligence(issueId)
  const storyArcCards = useIssueCards(metadata?.story_arcs.flatMap((arc) => arc.related_issues.flatMap((related) => related.comicpile_matches.map((match) => match.issue_id))) ?? [], { enabled: !isLoading })
  const cardsByIssue = indexIssueCards(storyArcCards.data)
  const [coverRatios, setCoverRatios] = useState<Record<string, number>>({})
  const [showAllCreators, setShowAllCreators] = useState(false)
  const [showAllStoryArcs, setShowAllStoryArcs] = useState(false)
  const [showAllRelatedIssues, setShowAllRelatedIssues] = useState<Record<number, boolean>>({})
  const [summaryExpanded, setSummaryExpanded] = useState(false)
  const [isModalOpen, setIsModalOpen] = useState(false)
  const creatorsDetailsRef = useRef<HTMLDetailsElement>(null)
  const storyArcsDetailsRef = useRef<HTMLDetailsElement>(null)
  const { isDesktop } = useResponsive()
  // One shared presentation/action contract for this exact owned issue. No
  // per-page retry, no timers and no polling (#5841).
  const metadataHydration = useComicVineMetadataHydration({
    issueId,
    metadata,
    refetchIntelligence: refetch,
  })

  useEffect(() => {
    setSummaryExpanded(false)
  }, [metadata?.comicvine_issue_id])

  useEffect(() => {
    if (creatorsDetailsRef.current) {
      creatorsDetailsRef.current.open = true
    }
    if (storyArcsDetailsRef.current) {
      storyArcsDetailsRef.current.open = true
    }
  }, [metadata])

  const imageUrl = metadata?.image_url ?? null
  const coverRatio = imageUrl ? coverRatios[imageUrl] ?? null : null
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
    if (!metadata) return []
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

  if (!issueId) return null
  if (isLoading) {
    return (
      <div
        data-testid="comic-cover"
        data-cover-aspect-ratio={coverAspectRatio}
        data-cover-height-cap-vh={COVER_HEIGHT_CAP_VH}
        data-cover-width-cap-vh={coverWidthCapVh}
        aria-label="Loading comic details"
        className="relative mx-auto overflow-hidden rounded-xl bg-[var(--theme-bg-hover)] animate-pulse"
        style={{ ...coverStyle, ...coverFrameBorder }}
      />
    )
  }
  if (isError) {
    return (
      <div role="alert" className="surface-panel space-y-2 rounded-xl p-3 text-sm">
        <p className="text-[var(--theme-error)]">
          Could not load comic details{error ? `: ${error.message}` : '.'}
        </p>
        <button
          type="button"
          onClick={() => void refetch()}
          className="min-h-11 rounded-lg px-3 font-bold text-[var(--theme-primary-action)] hover:underline"
        >
          Retry comic details
        </button>
      </div>
    )
  }
  if (!metadata) return null

  const date = formatDate(metadata.store_date) ?? formatDate(metadata.cover_date)
  const creatorsToShow = showAllCreators ? metadata.creators : metadata.creators.slice(0, CREATOR_LIMIT)
  const hasMoreCreators = metadata.creators.length > CREATOR_LIMIT
  const isLongSummary = metadata.description != null && metadata.description.length > SUMMARY_LONG_THRESHOLD

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
        className="relative mx-auto overflow-hidden rounded-xl bg-[var(--theme-bg-hover)]"
        style={{ ...coverStyle, ...coverFrameBorder }}
      >
        <ComicIssueCover
          coverImageUrl={metadata.image_url}
          threadTitle={metadata.series_name ?? 'Comic'}
          issueNumber={metadata.issue_number ?? '?'}
          variant="featured"
          frameClassName="h-full w-full"
          frameStyle={{ aspectRatio: 'auto' }}
          imageClassName="h-full w-full object-contain"
          altText=""
          placeholderTestId="cover-placeholder"
          onImageLoad={(img) => {
            const { naturalWidth, naturalHeight } = img
            const currentImageUrl = metadata?.image_url
            if (naturalWidth > 0 && naturalHeight > 0 && currentImageUrl) {
              const nextRatio = naturalWidth / naturalHeight
              setCoverRatios((previous) => {
                if (previous[currentImageUrl] === nextRatio) return previous
                return { ...previous, [currentImageUrl]: nextRatio }
              })
            }
          }}
        >
          <div className="absolute bottom-2 left-2 right-2 flex justify-end gap-1.5">
            <button
              type="button"
              onClick={() => setIsModalOpen(true)}
              className="inline-flex items-center justify-center w-7 h-7 rounded-md bg-[var(--theme-bg-page)]/60 text-[var(--theme-text-primary)] hover:text-[var(--theme-text-primary)] hover:bg-[var(--theme-bg-page)]/80 transition-colors focus:ring-2 focus:ring-[var(--theme-focus-ring)]"
              aria-label="View cover larger"
              title="View larger"
            >
              <EyeIcon className="w-4 h-4" />
            </button>
            {metadata.comicvine_url && (
              <a
                href={metadata.comicvine_url}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center justify-center w-7 h-7 rounded-md bg-[var(--theme-bg-page)]/60 text-[var(--theme-text-primary)] hover:text-[var(--theme-text-primary)] hover:bg-[var(--theme-bg-page)]/80 transition-colors focus:ring-2 focus:ring-[var(--theme-focus-ring)]"
                aria-label="Open on ComicVine"
                title="Open in ComicVine"
              >
                <ArrowTopRightOnSquareIcon className="w-4 h-4" />
              </a>
            )}
          </div>
        </ComicIssueCover>
      </div>

      <div className="space-y-3">
        {date && (
          <p className="text-[11px] text-[var(--theme-text-dim)]">{date}</p>
        )}

        {metadata.description && (
          <details
            className="group space-y-2"
            {...(isDesktop ? { open: true } : {})}
          >
            <summary className="flex items-center gap-2 cursor-pointer list-none focus:ring-2 focus:ring-[var(--theme-focus-ring)] rounded-lg p-2 hover:bg-[var(--theme-bg-hover)] transition-colors">
              <span className="text-[10px] font-black uppercase tracking-wider text-[var(--theme-text-muted)]">Summary</span>
              <span className="text-[var(--theme-text-dim)] group-open:rotate-180 transition-transform" aria-hidden="true">⌄</span>
            </summary>
            <div
              data-testid="comic-summary"
              className="pl-6 pr-2 pb-2 text-xs leading-relaxed text-[var(--theme-text-primary)] border-l border-[var(--theme-border)]"
            >
              {isLongSummary && !summaryExpanded ? (
                <>
                  <p>{metadata.description!.slice(0, SUMMARY_LONG_THRESHOLD)}…</p>
                  <button
                    type="button"
                    onClick={() => setSummaryExpanded(true)}
                    className="mt-1 inline-flex min-h-6 items-center text-[10px] font-bold text-[var(--theme-comic-accent)] hover:text-[var(--theme-comic-accent)] focus:ring-2 focus:ring-[var(--theme-focus-ring)] rounded"
                    aria-expanded={summaryExpanded}
                  >
                    Show more
                  </button>
                </>
              ) : (
                <>
                  <p>{metadata.description}</p>
                  {isLongSummary && (
                    <button
                      type="button"
                      onClick={() => setSummaryExpanded(false)}
                      className="mt-1 inline-flex min-h-6 items-center text-[10px] font-bold text-[var(--theme-comic-accent)] hover:text-[var(--theme-comic-accent)] focus:ring-2 focus:ring-[var(--theme-focus-ring)] rounded"
                      aria-expanded={!summaryExpanded}
                    >
                      Show less
                    </button>
                  )}
                </>
              )}
            </div>
          </details>
        )}

        {metadata.creators.length > 0 && (
          <>
            {metadata.description && <hr className="border-[var(--theme-border)] my-1" />}
            <details ref={creatorsDetailsRef} className="group space-y-2">
            <summary className="flex items-center gap-2 cursor-pointer list-none focus:ring-2 focus:ring-[var(--theme-focus-ring)] rounded-lg p-2 hover:bg-[var(--theme-bg-hover)] transition-colors">
              <span className="text-[10px] font-black uppercase tracking-wider text-[var(--theme-text-muted)]">Creators</span>
              <span className="ml-auto text-[var(--theme-text-dim)] group-open:rotate-180 transition-transform" aria-hidden="true">⌄</span>
            </summary>
            <div id="creators-list" className="pl-6 pr-2 pb-2 space-y-1 border-l border-[var(--theme-border)]">
              {creatorsToShow.map((creator, index) => {
                const stableKey = creator.creator_id != null ? canonicalCreatorKey(creator.creator_id) : null
                const summary = stableKey ? summaries[stableKey] : undefined
                const hasRatedStats = summary != null
                const upcomingVisible =
                  summary != null &&
                  coverage != null &&
                  (coverage.upcoming_complete || summary.upcoming_count > 0)
                        return (
                             <div
                               key={`${creator.name}-${index}`}
                               data-testid="creator-row"
                               className="flex flex-col gap-0.5 py-1 border-b border-[var(--theme-border)] last:border-none flex-wrap break-words min-w-0"
                             >
                            <div className="flex items-baseline gap-x-1.5 min-w-0">
                              <span className="font-bold text-[var(--theme-text-primary)] break-words min-w-0">{creator.name}</span>
                              {creator.roles.length > 0 && (
                                <span className="text-[var(--theme-text-dim)] text-[11px] break-words min-w-0">
                                  {creator.roles.join(', ')}
                                </span>
                              )}
                            </div>
                            <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[10px] text-[var(--theme-text-muted)] min-w-0">
                                 {hasRatedStats && summary.average_rating != null ? (
                                   <>
                                     <span
                                       className="inline-flex items-center gap-0.5"
                                       aria-label={`Average rating ${formatRating(summary.average_rating)} out of 5 from ${summary.ratings_count} ${summary.ratings_count === 1 ? 'rating' : 'ratings'}${coverage && !coverage.ratings_complete ? ', partial coverage — lower bound' : ''}`}
                                     >
                                       <span aria-hidden="true" className="text-[var(--theme-comic-accent)]/80">
                                         ★
                                       </span>
                                       <span>{formatRating(summary.average_rating)}</span>
                                     </span>
                                     <span>
                                       {summary.ratings_count}
                                       {coverage && !coverage.ratings_complete && summary.ratings_count > 0 ? '+' : ''} rated
                                     </span>
                                   </>
                                 ) : hasRatedStats ? (
                                   <span className="inline-flex items-center gap-0.5">0 rated</span>
                                 ) : null}
                              {upcomingVisible ? (
                                <span
                                  className="inline-flex items-center gap-0.5"
                                  aria-label={coverage!.upcoming_complete ? `${summary!.upcoming_count} unread` : `At least ${summary!.upcoming_count} unread, partial coverage`}
                                >
                                  {summary!.upcoming_count}{coverage && !coverage.upcoming_complete && summary!.upcoming_count > 0 ? '+' : ''} unread
                                </span>
                              ) : null}
                            </div>
                          </div>
                        )
              })}
            </div>
            {hasMoreCreators && (
              <button
                type="button"
                onClick={() => setShowAllCreators(!showAllCreators)}
                className="ml-6 inline-flex min-h-6 items-center text-[10px] font-bold text-[var(--theme-comic-accent)] hover:text-[var(--theme-comic-accent)] focus:ring-2 focus:ring-[var(--theme-focus-ring)] rounded"
                aria-expanded={showAllCreators}
                aria-controls="creators-list"
              >
                {showAllCreators ? 'Show less' : `Show all ${metadata.creators.length}`}
              </button>
            )}
            </details>
          </>
        )}

        {/* Shared exact-issue presentation/action contract: truthful state and
            one explicit Retry, never a queued spinner or a polling loop. */}
        {metadata.creators.length === 0 && (
          <div className="pl-6 pr-2 pb-2 border-l border-[var(--theme-border)]">
            <ComicVineMetadataStatus state={metadataHydration} />
          </div>
        )}

        {metadata.story_arcs.length > 0 && (
          <details ref={storyArcsDetailsRef} className="group space-y-3">
            <summary className="flex items-center gap-2 cursor-pointer list-none focus:ring-2 focus:ring-[var(--theme-focus-ring)] rounded-lg p-2 hover:bg-[var(--theme-bg-hover)] transition-colors">
              <span className="text-[10px] font-black uppercase tracking-wider text-[var(--theme-text-muted)]">
                Story arcs ({metadata.story_arcs.length})
              </span>
            </summary>
            <div className="pl-6 pr-2 pb-2 space-y-3 border-l border-[var(--theme-border)]">
              {metadata.story_arcs
                .slice(0, showAllStoryArcs ? metadata.story_arcs.length : STORY_ARC_LIMIT)
                .map((arc) => {
                  const isExpanded = showAllRelatedIssues[arc.comicvine_arc_id]
                  const displayedIssues = isExpanded ? arc.related_issues : arc.related_issues.slice(0, RELATED_ISSUES_PER_ARC_LIMIT)
                  const hasMore = arc.related_issues.length > RELATED_ISSUES_PER_ARC_LIMIT

                  return (
                    <section key={arc.comicvine_arc_id} className="space-y-2">
                      <h3 className="text-xs font-bold text-[var(--theme-continuity-accent)]">{normalizeArcName(arc.name)}</h3>
                      <p className="text-[9px] text-[var(--theme-text-dim)]">
                        {arc.related_issues.filter((issue) => issue.comicpile_matches.length > 0).length} in ComicPile ·{' '}
                        {arc.related_issues.filter((issue) => issue.comicpile_matches.length === 0).length} missing
                        {arc.total_related_count != null && arc.total_related_count > arc.related_issues.length && (
                          <span className="ml-1 text-[var(--theme-text-muted)]">({arc.related_issues.length} of {arc.total_related_count} shown)</span>
                        )}
                      </p>
                      <p className="text-[9px] text-[var(--theme-text-dim)]">Related by story-arc membership, not reading order.</p>
                      <div className="space-y-1.5" data-testid="story-arc-issue-list">
                        {displayedIssues.map((issue) => {
                          const identity = extractComicIdentity(issue, issue.comicpile_matches)
                          const state = getMemberState(issue)
                          const stateLabel = getStateLabel(state)
                          const stateColorClass = getStateColorClass(state)

                          return (
                            <div key={issue.comicvine_issue_id} className="p-2 rounded-lg bg-[var(--theme-bg-page)]/15 border border-[var(--theme-border)]">
                              <div className="flex gap-2 justify-between items-start">
                                <div className="flex-1 min-w-0">
                                  <span className="text-[11px] font-bold text-[var(--theme-text-primary)] truncate block">{identity.primary}</span>
                                  {identity.secondary && (
                                    <span className="text-[10px] text-[var(--theme-text-dim)] truncate block">{identity.secondary}</span>
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
                                      className="inline-flex min-h-6 items-center text-[9px] font-bold text-[var(--theme-comic-accent)] hover:text-[var(--theme-comic-accent)] shrink-0 px-2 rounded border border-[var(--theme-comic-accent)]/30 bg-[var(--theme-comic-accent)]/10 transition-colors focus:ring-2 focus:ring-[var(--theme-focus-ring)]"
                                      aria-label={`Add ${identity.primary} to ComicPile`}
                                    >
                                      Add to ComicPile
                                    </button>
                                  )}
                                </div>
                              </div>
                              {issue.comicpile_matches.map((match) => (
                                <CompactIssueCardTrigger
                                  key={match.issue_id}
                                  issueId={match.issue_id}
                                  card={cardsByIssue.get(match.issue_id)}
                                  threadTitle={match.thread_title}
                                  issueNumber={match.issue_number}
                                  status={match.status}
                                  hideTitle={issue.comicpile_matches.length === 1}
                                />
                              ))}
                            </div>
                          )
                        })}
                        {hasMore && (
                          <button
                            type="button"
                            onClick={() => setShowAllRelatedIssues((prev) => ({ ...prev, [arc.comicvine_arc_id]: !prev[arc.comicvine_arc_id] }))}
                            className="w-full inline-flex min-h-6 items-center text-left text-[10px] font-bold text-[var(--theme-comic-accent)] hover:text-[var(--theme-comic-accent)] focus:ring-2 focus:ring-[var(--theme-focus-ring)] rounded"
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
                        className="inline-flex min-h-8 items-center text-xs font-bold text-[var(--theme-continuity-accent)] hover:text-[var(--theme-continuity-accent)] mt-2"
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
                  className="w-full inline-flex min-h-6 items-center text-left text-[10px] font-bold text-[var(--theme-comic-accent)] hover:text-[var(--theme-comic-accent)] focus:ring-2 focus:ring-[var(--theme-focus-ring)] rounded"
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
            className="inline-flex min-h-11 items-center text-xs font-bold text-[var(--theme-comic-accent)] hover:text-[var(--theme-comic-accent)] focus:ring-2 focus:ring-[var(--theme-focus-ring)] rounded-lg px-2"
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
    <Modal
      isOpen={isModalOpen}
      title="Comic Cover"
      onClose={() => setIsModalOpen(false)}
      data-testid="cover-viewer-modal"
      size="large"
    >
      {metadata.image_url && (
        <ImageWithLoading
          src={metadata.image_url}
          alt={metadata.name ?? 'Comic cover'}
          className="w-full rounded-lg"
        />
      )}
    </Modal>
    </>
  )
}
