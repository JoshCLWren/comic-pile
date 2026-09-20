import { useState, useEffect, useCallback } from 'react'
import IssueCorrectionDialog from '../../../components/IssueCorrectionDialog'
import ComicVineSearchDialog from '../../../components/ComicVineSearchDialog'
import { comicVineApi, type ComicVineIssueCandidate, type IssueIdentityResponse } from '../../../services/api'
import { getProgressPercentage } from '../utils'
import type { RatingThread } from '../types'
import { queryClient } from '../../../query/queryClient'
import {
  applyComicVineCorrectionOptimistically,
  invalidateComicVineIssueIntelligence,
} from '../../../query/cacheEffects'

interface ConsolidatedComicCardProps {
  activeRatingThread: RatingThread | null
  identityState: IssueIdentityResponse | null
  onFixIssueNumber: () => void
  onWrongSeries: () => void
  onFindComicVineMatch: () => void
}

function ConsolidatedComicCard({
  activeRatingThread,
  identityState,
  onFixIssueNumber,
  onWrongSeries,
  onFindComicVineMatch,
}: ConsolidatedComicCardProps) {
  const issueNumber = activeRatingThread?.next_issue_number ?? activeRatingThread?.issue_number ?? null
  const totalIssues = activeRatingThread?.total_issues ?? null
  const issuesRemaining = activeRatingThread?.issues_remaining ?? 0
  const progress = getProgressPercentage(activeRatingThread)
  const needsIdentity = identityState && !identityState.has_confirmed_identity

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
            className="relative mx-auto overflow-hidden rounded-xl bg-white/5"
            style={{ 
              aspectRatio: '2/3',
              width: 'min(100%, calc(30vh))',
              border: '1px solid var(--theme-border)'
            }}
          >
            <div data-testid="cover-placeholder" className="w-full h-full flex items-center justify-center text-stone-600" aria-hidden="true">
              <svg className="w-16 h-16" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 002 2v12z" />
              </svg>
            </div>
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

            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] font-bold text-stone-500">
              {totalIssues && issueNumber != null ? (
                <span>Issue {issueNumber} of {totalIssues}</span>
              ) : null}
              {totalIssues && issueNumber != null ? <span aria-hidden="true">·</span> : null}
              <span>{progress}% complete</span>
              <span aria-hidden="true">·</span>
              <span>{issuesRemaining} left</span>
            </div>

            {/* Publication date placeholder - will be added when ComicVine data is available */}
            <div className="text-[11px] text-stone-500">
              {/* Publication date will be displayed here when available */}
            </div>
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

        {/* Creator info section - simplified version */}
        <div className="space-y-3 pt-3 border-t border-white/10">
          <div className="flex items-center gap-2">
            <span className="text-[10px] font-black uppercase tracking-wider text-stone-400">Creators</span>
          </div>
          <div className="text-xs text-stone-300">
            {/* Creator information will be displayed here when available */}
          </div>
        </div>
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

  const issueId = activeRatingThread?.issue_id ?? activeRatingThread?.next_issue_id

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

  return (
    <>
      <ConsolidatedComicCard
        activeRatingThread={activeRatingThread}
        identityState={identityState}
        onFixIssueNumber={handleFixIssueNumber}
        onWrongSeries={handleWrongSeries}
        onFindComicVineMatch={handleFindComicVineMatch}
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
