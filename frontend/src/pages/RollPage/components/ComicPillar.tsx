import { useState, useEffect, useCallback } from 'react'
import IssueCorrectionDialog from '../../../components/IssueCorrectionDialog'
import ComicVineSearchDialog from '../../../components/ComicVineSearchDialog'
import { comicVineApi, type ComicVineIssueCandidate, type IssueIdentityResponse } from '../../../services/api'
import { getProgressPercentage } from '../utils'
import type { RatingThread } from '../types'
import { ComicIdentity } from './ComicIdentity'
import { queryClient } from '../../../query/queryClient'
import {
  applyComicVineCorrectionOptimistically,
  invalidateComicVineIssueIntelligence,
} from '../../../query/cacheEffects'

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

  const threadTitle = activeRatingThread?.title ?? 'Loading…'
  const issueNumber = activeRatingThread?.next_issue_number ?? activeRatingThread?.issue_number ?? null
  const issueId = activeRatingThread?.issue_id ?? activeRatingThread?.next_issue_id
  const totalIssues = activeRatingThread?.total_issues ?? null
  const issuesRemaining = activeRatingThread?.issues_remaining ?? 0
  const progress = getProgressPercentage(activeRatingThread)

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

  const needsIdentity = identityState && !identityState.has_confirmed_identity

  return (
    <div className="w-full space-y-4">
      {/* Cover rail beside issue identity/details composition */}
      <div className="flex flex-col lg:flex-row gap-4">
        {/* Cover rail */}
        <div className="flex-shrink-0 w-full lg:w-auto">
          <ComicIdentity issueId={issueId} />
        </div>

        {/* Issue identity and details */}
        <div className="flex-1 space-y-3" data-testid="comic-header-row">
          {/* Provider eyebrow and title block */}
          <div className="space-y-2">
            {identityState?.has_confirmed_identity && (
              <div className="text-[10px] font-black uppercase tracking-[0.18em]" style={{ color: 'var(--theme-comic-accent)' }}>
                COMICVINE #{identityState.comicvine_issue_id}
              </div>
            )}
            <div className="flex flex-col gap-1">
              <h2 data-testid="comic-header-title" className="text-xl font-black text-stone-100 leading-tight break-words">
                {threadTitle}
                {issueNumber != null ? <span style={{ color: 'var(--theme-comic-accent)' }}> #{issueNumber}</span> : null}
              </h2>
              {issueNumber != null && totalIssues != null && (
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] font-bold text-stone-500">
                  <span>Issue {issueNumber} of {totalIssues}</span>
                  <span aria-hidden="true">·</span>
                  <span>{progress}% complete</span>
                  <span aria-hidden="true">·</span>
                  <span>{issuesRemaining} left</span>
                </div>
              )}
            </div>
          </div>

          {/* Compact identity/correction controls */}
          {issueNumber != null && (
            <div className="flex flex-wrap items-center gap-2" data-testid="comic-header-controls">
              <button
                type="button"
                onClick={() => setIsCorrectionDialogOpen(true)}
                disabled={!activeRatingThread?.id}
                className="min-h-9 rounded-lg px-3 text-[10px] font-black uppercase tracking-wider text-stone-300 transition disabled:opacity-30"
                style={{
                  border: '1px solid rgba(255,255,255,0.1)',
                  backgroundColor: 'rgba(255,255,255,0.05)',
                }}
                aria-label="Fix issue number"
              >
                Fix issue #
              </button>
              
              {needsIdentity && issueId && (
                <button
                  type="button"
                  onClick={() => { setSearchMode('confirm'); setIsSearchDialogOpen(true) }}
                  className="min-h-9 rounded-lg px-3 text-[10px] font-black uppercase tracking-wider text-stone-900 bg-amber-500 hover:bg-amber-400 transition shrink-0"
                >
                  Find ComicVine match
                </button>
              )}

              {identityState?.has_confirmed_identity && issueId && (
                <div className="flex items-center gap-2">
                  <div className="flex items-center gap-1 rounded-full px-2 py-1 bg-green-500/10 border border-green-500/30">
                    <div className="w-1.5 h-1.5 rounded-full bg-green-500"></div>
                    <span className="text-[9px] font-bold text-green-400">Linked</span>
                  </div>
                  <button
                    type="button"
                    onClick={() => { setSearchMode('replace'); setIsSearchDialogOpen(true) }}
                    className="min-h-9 rounded-lg px-3 text-[10px] font-black uppercase tracking-wider text-stone-400 hover:text-amber-400 transition shrink-0"
                    style={{
                      border: '1px solid rgba(255,255,255,0.1)',
                      backgroundColor: 'rgba(255,255,255,0.05)',
                    }}
                  >
                    Wrong series?
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Rich content continues in ComicIdentity component */}

      {activeRatingThread ? (
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
      ) : null}

      {issueId && (
        <ComicVineSearchDialog
          isOpen={isSearchDialogOpen}
          issueId={issueId}
          threadTitle={threadTitle}
          issueNumber={issueNumber}
          mode={searchMode}
          onClose={() => setIsSearchDialogOpen(false)}
          onConfirmed={handleIdentityConfirmed}
        />
      )}
    </div>
  )
}
