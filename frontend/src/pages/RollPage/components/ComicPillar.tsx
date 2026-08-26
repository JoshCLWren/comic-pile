import { useState, useEffect, useCallback } from 'react'
import IssueCorrectionDialog from '../../../components/IssueCorrectionDialog'
import ComicVineSearchDialog from '../../../components/ComicVineSearchDialog'
import { comicVineApi, type IssueIdentityResponse } from '../../../services/api'
import { getProgressPercentage } from '../utils'
import type { RatingThread } from '../types'
import { ComicIdentity } from './ComicIdentity'

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
  const [copyStatus, setCopyStatus] = useState<'idle' | 'copied' | 'failed'>('idle')
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

  const handleIdentityConfirmed = useCallback(() => {
    fetchIdentity()
    onRefreshThread()
  }, [fetchIdentity, onRefreshThread])

  const needsIdentity = identityState && !identityState.has_confirmed_identity

  async function handleCopyComicReference() {
    if (!activeRatingThread?.title || issueNumber == null) return

    try {
      await navigator.clipboard.writeText(`${activeRatingThread.title} ${issueNumber}`)
      setCopyStatus('copied')
    } catch {
      setCopyStatus('failed')
    }
  }

  return (
    <div className="w-full space-y-4">
      <div className="flex items-center gap-2 border-b-2 pb-2" style={{ borderColor: 'var(--theme-comic-accent)' }}>
        <span className="text-[10px] font-black uppercase tracking-[0.18em]" style={{ color: 'var(--theme-comic-accent)' }}>The Comic</span>
      </div>
      <section id="thread-info" aria-labelledby="selected-issue-heading" className="space-y-3">
        <div className="rounded-2xl p-3 md:p-4" style={{ border: '1px solid rgba(212,137,14,0.2)', backgroundColor: 'var(--theme-bg-panel)' }}>
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="text-[10px] font-black uppercase tracking-[0.18em] text-stone-500">
                Selected issue
              </p>
              <h2 id="selected-issue-heading" className="mt-1 text-xl font-black leading-tight text-stone-100">
                {threadTitle}
                {issueNumber != null ? <span style={{ color: 'var(--theme-comic-accent)' }}> #{issueNumber}</span> : null}
              </h2>
            </div>
            {issueNumber != null ? (
              <div className="flex shrink-0 gap-1.5">
                <button
                  type="button"
                  onClick={handleCopyComicReference}
                  disabled={!activeRatingThread?.title}
                  className="min-h-11 rounded-xl px-3 text-[10px] font-black uppercase tracking-wider text-stone-300 transition disabled:opacity-30"
                  style={{
                    border: '1px solid rgba(255,255,255,0.1)',
                    backgroundColor: 'rgba(255,255,255,0.05)',
                  }}
                  aria-label={`Copy ${threadTitle} ${issueNumber}`}
                >
                  {copyStatus === 'copied' ? 'Copied' : copyStatus === 'failed' ? 'Retry copy' : 'Copy title'}
                </button>
                <button
                  type="button"
                  onClick={() => setIsCorrectionDialogOpen(true)}
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
            ) : null}
          </div>

          {copyStatus === 'failed' ? (
            <p className="mt-2 text-[10px] font-bold text-rose-400" role="status">
              Copy failed. Use Retry copy to try again.
            </p>
          ) : null}

          <div className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] font-bold text-stone-500">
            {totalIssues && issueNumber != null ? (
              <span>Issue {issueNumber} of {totalIssues}</span>
            ) : null}
            {totalIssues && issueNumber != null ? <span aria-hidden="true">·</span> : null}
            <span>{progress}% complete</span>
            <span aria-hidden="true">·</span>
            <span>{issuesRemaining} left</span>
          </div>
        </div>
      </section>

      {needsIdentity && issueId && (
        <div
          className="rounded-xl p-3 flex items-center justify-between gap-3"
          style={{
            border: '1px solid rgba(234,179,8,0.25)',
            backgroundColor: 'rgba(234,179,8,0.06)',
          }}
        >
          <p className="text-xs text-amber-300/90 font-bold">
            No ComicVine identity linked
          </p>
          <button
            type="button"
            onClick={() => { setSearchMode('confirm'); setIsSearchDialogOpen(true) }}
            className="min-h-9 rounded-lg px-3 text-[10px] font-black uppercase tracking-wider text-stone-900 bg-amber-500 hover:bg-amber-400 transition shrink-0"
          >
            Find ComicVine match
          </button>
        </div>
      )}

      {identityState?.has_confirmed_identity && issueId && (
        <div
          className="rounded-xl p-3 flex items-center justify-between gap-3"
          style={{
            border: '1px solid rgba(255,255,255,0.08)',
            backgroundColor: 'rgba(255,255,255,0.03)',
          }}
        >
          <p className="text-[10px] text-stone-500 font-bold">ComicVine linked</p>
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

      <ComicIdentity issueId={issueId} />

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
