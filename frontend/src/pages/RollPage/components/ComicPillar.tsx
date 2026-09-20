import { useState, useEffect, useCallback, type CSSProperties } from 'react'
import IssueCorrectionDialog from '../../../components/IssueCorrectionDialog'
import ComicVineSearchDialog from '../../../components/ComicVineSearchDialog'
import ImageWithLoading from '../../../components/ImageWithLoading'
import { comicVineApi, type ComicVineIssueCandidate, type IssueIdentityResponse, type ComicVineIssueIntelligence } from '../../../services/api'
import { useComicVineIssueIntelligence } from '../../../hooks/useComicVineIssueIntelligence'
import { optimizedImageSrcSet, optimizedImageUrl } from '../../../services/imageDelivery'
import { getProgressPercentage } from '../utils'
import type { RatingThread } from '../types'
import { queryClient } from '../../../query/queryClient'
import {
  applyComicVineCorrectionOptimistically,
  invalidateComicVineIssueIntelligence,
} from '../../../query/cacheEffects'

const CREATOR_LIMIT = 6
const COVER_HEIGHT_CAP_VH = 45
const COVER_RATIO_FALLBACK = 2 / 3

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

interface ConsolidatedComicCardProps {
  activeRatingThread: RatingThread | null
  identityState: IssueIdentityResponse | null
  metadata: ComicVineIssueIntelligence | null
  isLoading: boolean
  failedImageUrl: string | null
  coverRatio: number | null
  onFixIssueNumber: () => void
  onWrongSeries: () => void
  onFindComicVineMatch: () => void
  onImageLoad: (naturalWidth: number, naturalHeight: number) => void
  onImageError: (url: string) => void
}

function ConsolidatedComicCard({
  activeRatingThread,
  identityState,
  metadata,
  isLoading,
  failedImageUrl,
  coverRatio,
  onFixIssueNumber,
  onWrongSeries,
  onFindComicVineMatch,
  onImageLoad,
  onImageError,
}: ConsolidatedComicCardProps) {
  const issueNumber = activeRatingThread?.next_issue_number ?? activeRatingThread?.issue_number ?? null
  const totalIssues = activeRatingThread?.total_issues ?? null
  const issuesRemaining = activeRatingThread?.issues_remaining ?? 0
  const progress = getProgressPercentage(activeRatingThread)
  const needsIdentity = identityState && !identityState.has_confirmed_identity

  const coverAspectRatio = coverRatio ?? COVER_RATIO_FALLBACK
  const coverWidthCapVh = COVER_HEIGHT_CAP_VH * coverAspectRatio
  const coverStyle: CSSProperties = {
    aspectRatio: `${coverAspectRatio}`,
    width: `min(100%, calc(${coverWidthCapVh}vh))`,
  }
  const coverFrameBorder = { border: '1px solid var(--theme-border)' }

  const date = metadata ? formatDate(metadata.store_date) ?? formatDate(metadata.cover_date) : null
  const creatorsToShow = metadata ? metadata.creators.slice(0, CREATOR_LIMIT) : []
  const hasMoreCreators = metadata ? metadata.creators.length > CREATOR_LIMIT : false

  return (
    <div className="w-full space-y-4">
      <div className="flex items-center gap-2 border-b-2 pb-2" style={{ borderColor: 'var(--theme-comic-accent)' }}>
        <span className="text-[10px] font-black uppercase tracking-[0.18em]" style={{ color: 'var(--theme-comic-accent)' }}>The Comic</span>
      </div>
      
      <section 
        id="consolidated-comic-card" 
        aria-labelledby="comic-identity-heading" 
        className="rounded-2xl p-4 space-y-4" 
        style={{ 
          border: '1px solid rgba(212,137,14,0.2)', 
          backgroundColor: 'var(--theme-bg-panel)' 
        }}
      >
        <div className="flex flex-col gap-4">
          {/* Cover image area */}
          <div 
            data-testid="comic-cover"
            data-cover-aspect-ratio={coverAspectRatio}
            data-cover-height-cap-vh={COVER_HEIGHT_CAP_VH}
            data-cover-width-cap-vh={coverWidthCapVh}
            className="relative mx-auto overflow-hidden rounded-xl bg-white/5"
            style={{ ...coverStyle, ...coverFrameBorder }}
          >
            {isLoading && <div className="absolute inset-0 animate-pulse bg-white/10" aria-hidden="true" />}
            {metadata && metadata.image_url && metadata.image_url !== failedImageUrl ? (
              <ImageWithLoading
                src={optimizedImageUrl(metadata.image_url, 720) ?? metadata.image_url}
                srcSet={optimizedImageSrcSet(metadata.image_url, [240, 480, 720]) ?? undefined}
                sizes="(min-width: 1024px) 30vh, calc((45vh * 2) / 3)"
                alt=""
                loading="eager"
                className="h-full w-full object-contain"
                placeholderClassName="animate-pulse bg-white/10"
                onLoad={(img) => onImageLoad(img.naturalWidth, img.naturalHeight)}
                onError={() => onImageError(metadata.image_url!)}
              />
            ) : (
              <div data-testid="cover-placeholder" className="w-full h-full flex items-center justify-center text-stone-600" aria-hidden="true">
                <svg className="w-16 h-16" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 002 2v12z" />
                </svg>
              </div>
            )}
          </div>

          {/* Comic identity and progress */}
          <div className="flex flex-col gap-3">
            <div className="flex flex-wrap items-start justify-between gap-3" data-testid="comic-header-row">
              <div className="min-w-[12rem] flex-1 basis-48 break-words" data-testid="comic-header-title">
                <h2 id="comic-identity-heading" className="mt-1 text-xl font-black leading-tight text-stone-100 break-words">
                  {activeRatingThread?.title}
                  {issueNumber != null && (
                    <span style={{ color: 'var(--theme-comic-accent)' }}> #{issueNumber}</span>
                  )}
                </h2>
              </div>
              {issueNumber != null && (
                <div className="flex shrink-0 flex-wrap gap-1.5" data-testid="comic-header-controls">
                  <button
                    type="button"
                    onClick={onFixIssueNumber}
                    disabled={!activeRatingThread?.id}
                    className="min-h-11 rounded-xl px-3 text-[10px] font-black uppercase tracking-wider text-stone-300 transition disabled:opacity-30"
                    style={{
                      border: '1px solid rgba(255,255,255,0.1)',
                      backgroundColor: 'rgba(255,255,255,0.05)',
                    }}
                    aria-label="Fix issue number"
                  >
                    Fix issue #
                  </button>
                </div>
              )}
            </div>

            {metadata && metadata.name && (
              <h3 className="text-lg font-bold text-stone-100 leading-tight">{metadata.name}</h3>
            )}

            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] font-bold text-stone-500">
              {totalIssues && issueNumber != null ? (
                <span>Issue {issueNumber} of {totalIssues}</span>
              ) : null}
              {totalIssues && issueNumber != null ? <span aria-hidden="true">·</span> : null}
              <span>{progress}% complete</span>
              <span aria-hidden="true">·</span>
              <span>{issuesRemaining} left</span>
            </div>

            {date && (
              <p className="text-[11px] text-stone-500">{date}</p>
            )}
          </div>

          {/* ComicVine linked status */}
          {identityState?.has_confirmed_identity && (
            <p className="text-[10px] text-stone-500 font-bold">ComicVine linked</p>
          )}

          {/* Correction controls in subordinate location */}
          <div className="flex flex-wrap gap-2 pt-2 border-t border-white/10">
            {identityState?.has_confirmed_identity && (
              <button
                type="button"
                onClick={onWrongSeries}
                className="min-h-9 rounded-lg px-3 text-[10px] font-black uppercase tracking-wider text-stone-400 hover:text-amber-400 transition shrink-0"
                style={{
                  border: '1px solid rgba(255,255,255,0.1)',
                  backgroundColor: 'rgba(255,255,255,0.05)',
                }}
                aria-label="Wrong series?"
              >
                Wrong series?
              </button>
            )}
            
            {needsIdentity && (
              <button
                type="button"
                onClick={onFindComicVineMatch}
                className="min-h-9 rounded-lg px-3 text-[10px] font-black uppercase tracking-wider text-stone-900 bg-amber-500 hover:bg-amber-400 transition shrink-0"
                aria-label="Find ComicVine match"
              >
                Find ComicVine match
              </button>
            )}
          </div>

          {/* ComicVine status - only show for missing identity */}
          {needsIdentity && (
            <div className="mt-3 p-3 rounded-lg bg-amber-500/10 border border-amber-500/30">
              <p className="text-xs text-amber-300/90 font-bold">
                No ComicVine identity linked
              </p>
            </div>
          )}
        </div>

        {/* Description section */}
        {metadata && metadata.description && (
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

        {/* Creator info section */}
        {metadata && metadata.creators.length > 0 && (
          <div className="space-y-3 pt-3 border-t border-white/10">
            <details className="group space-y-2">
              <summary className="flex items-center gap-2 cursor-pointer list-none focus:ring-2 focus:ring-amber-500 rounded-lg p-2 hover:bg-white/5 transition-colors">
                <span className="text-[10px] font-black uppercase tracking-wider text-stone-400">Creators</span>
                <span className="ml-auto text-stone-500 group-open:rotate-180 transition-transform" aria-hidden="true">⌄</span>
              </summary>
              <div className="pl-6 pr-2 pb-2 space-y-1 border-l border-white/10">
                {creatorsToShow.map((creator, index) => (
                  <p
                    key={`${creator.name}-${index}`}
                    className="flex flex-wrap items-baseline gap-x-1.5 gap-y-0.5 text-xs text-stone-300 min-w-0 break-words"
                  >
                    <span className="font-bold break-words min-w-0">{creator.name}</span>
                    {creator.roles.length > 0 && (
                      <span className="text-stone-500 break-words min-w-0">· {creator.roles.join(', ')}</span>
                    )}
                  </p>
                ))}
              </div>
              {hasMoreCreators && (
                <p className="ml-6 text-[10px] font-bold text-amber-500">
                  +{metadata.creators.length - CREATOR_LIMIT} more creators
                </p>
              )}
            </details>
          </div>
        )}
      </section>
    </div>
  )
}

interface ComicPillarProps {
  activeRatingThread: RatingThread | null
  onRefreshThread: () => void
}

export function ComicPillar({
  activeRatingThread,
  onRefreshThread,
}: ComicPillarProps) {
  const [isCorrectionDialogOpen, setIsCorrectionDialogOpen] = useState(false)
  const [isSearchDialogOpen, setIsSearchDialogOpen] = useState(false)
  const [identityState, setIdentityState] = useState<IssueIdentityResponse | null>(null)
  const [searchMode, setSearchMode] = useState<'confirm' | 'replace'>('confirm')
  const [failedImageUrl, setFailedImageUrl] = useState<string | null>(null)
  const [coverRatio, setCoverRatio] = useState<number | null>(null)

  const issueId = activeRatingThread?.issue_id ?? activeRatingThread?.next_issue_id

  const { metadata, isLoading } = useComicVineIssueIntelligence(issueId)

  useEffect(() => {
    setCoverRatio(null)
  }, [metadata?.image_url, isLoading])

  const fetchIdentity = useCallback(async () => {
    if (!issueId) {
      setIdentityState(null)
      return
    }
    try {
      const state = await comicVineApi.getIssueIdentity(issueId)
      setIdentityState(state)
    } catch {
      setIdentityState(null)
    }
  }, [issueId])

  useEffect(() => {
    fetchIdentity()
  }, [fetchIdentity])

  const handleIdentityConfirmed = useCallback(async (selected?: ComicVineIssueCandidate | null) => {
    if (issueId) {
      if (selected && selected.image_url !== undefined) {
        applyComicVineCorrectionOptimistically(queryClient, issueId, selected.image_url)
      }
      await invalidateComicVineIssueIntelligence(queryClient, issueId)
    }
    await fetchIdentity()
    onRefreshThread()
  }, [fetchIdentity, onRefreshThread, issueId])

  const handleFixIssueNumber = () => {
    setIsCorrectionDialogOpen(true)
  }

  const handleWrongSeries = () => {
    setSearchMode('replace')
    setIsSearchDialogOpen(true)
  }

  const handleFindComicVineMatch = () => {
    setSearchMode('confirm')
    setIsSearchDialogOpen(true)
  }

  const handleImageLoad = useCallback((naturalWidth: number, naturalHeight: number) => {
    if (naturalWidth > 0 && naturalHeight > 0) {
      setCoverRatio(naturalWidth / naturalHeight)
    }
  }, [])

  const handleImageError = useCallback((url: string) => {
    setFailedImageUrl(url)
  }, [])

  return (
    <>
      <ConsolidatedComicCard
        activeRatingThread={activeRatingThread}
        identityState={identityState}
        metadata={metadata}
        isLoading={isLoading}
        failedImageUrl={failedImageUrl}
        coverRatio={coverRatio}
        onFixIssueNumber={handleFixIssueNumber}
        onWrongSeries={handleWrongSeries}
        onFindComicVineMatch={handleFindComicVineMatch}
        onImageLoad={handleImageLoad}
        onImageError={handleImageError}
      />

      {/* Dialogs remain at the pillar level since they're shared */}
      {activeRatingThread && (
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
      )}

      {issueId && (
        <ComicVineSearchDialog
          isOpen={isSearchDialogOpen}
          issueId={issueId}
          threadTitle={activeRatingThread?.title ?? 'Loading…'}
          issueNumber={activeRatingThread?.next_issue_number ?? activeRatingThread?.issue_number ?? null}
          mode={searchMode}
          onClose={() => setIsSearchDialogOpen(false)}
          onConfirmed={handleIdentityConfirmed}
        />
      )}
    </>
  )
}
