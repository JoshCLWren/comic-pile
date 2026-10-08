import { useState, useEffect, useCallback, useMemo } from 'react'
import IssueCorrectionDialog from '../../../components/IssueCorrectionDialog'
import ComicVineSearchDialog from '../../../components/ComicVineSearchDialog'
import OverflowMenu, { type OverflowMenuItem } from '../../../components/OverflowMenu'
import { comicVineApi } from '../../../services/api-comicvine'
import type { ComicVineIssueCandidate } from '../../../services/api-comicvine'
import type { IssueIdentityResponse } from '../../../services/api-comicvine'
import { getProgressPercentage } from '../utils'
import type { RatingThread } from '../types'
import { ComicIdentity } from './ComicIdentity'
import { queryClient } from '../../../query/queryClient'
import {
  applyComicVineCorrectionOptimistically,
  invalidateComicVineIssueIntelligence,
  invalidateComicVineIssueIntelligenceMany,
} from '../../../query/cacheEffects'
import { useComicVineIssueIntelligence } from '../../../hooks/useComicVineIssueIntelligence'

interface ComicPillarProps {
  activeRatingThread: RatingThread | null
  /** Die size the current roll used, so the winning face can be named on the card (issue #3126). */
  currentDie?: number
  onRefreshThread: () => void
}

// A non-breaking space before the separator glues it to the item it follows, so
// a wrap can never strand a bare separator at the start of the next line.
const METADATA_SEPARATOR = '\u00a0· '

export function ComicPillar({
  activeRatingThread,
  currentDie,
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
  const { metadata } = useComicVineIssueIntelligence(issueId)
  const storyTitle = metadata?.name ?? null
  // The publication date is rendered once, beside the cover in ComicIdentity.
  // Repeating it here only produced two dates for the same issue.
  const progressItems = [
    ...(issueNumber != null && totalIssues != null
      ? [`Issue ${issueNumber} of ${totalIssues}`]
      : []),
    `${progress}% complete`,
    `${issuesRemaining} left`,
  ]

  // Issue #3126: the result card must name the face the roll actually produced,
  // otherwise the face-mapping list is the only cross-reference a reader has for
  // why this series was picked. Both facts are thread-scoped: the die face is the
  // roll that selected this thread, and queue position is 1-based, with 0 meaning
  // the payload carried no position rather than "first".
  const rolledFace = activeRatingThread?.last_rolled_result ?? null
  const queuePosition = activeRatingThread?.queue_position ?? 0
  const rollResultLine =
    rolledFace != null && currentDie != null
      ? `Rolled ${rolledFace} of d${currentDie}${
          queuePosition > 0 ? ` · #${queuePosition} in queue` : ''
        }`
      : null

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

  // Issue #3159: a confirmed volume correction can also confirm the series' other
  // numbered siblings in one step, so each confirmed sibling needs its own cover
  // refetched before the card can show the enriched series.
  const handleSiblingsMapped = useCallback(
    async (confirmedIssueIds: number[]) => {
      if (confirmedIssueIds.length > 0) {
        await invalidateComicVineIssueIntelligenceMany(queryClient, confirmedIssueIds)
      }
      onRefreshThread()
    },
    [onRefreshThread],
  )

  const needsIdentity = identityState && !identityState.has_confirmed_identity
  const isLinked = Boolean(identityState?.has_confirmed_identity)

  // Issue #3008: correction tools are occasional recovery actions, so they must
  // not compete with the title, cover, rating, and Mark read & save hierarchy
  // that follows the read/rate flow. They collapse into one quiet overflow
  // trigger, and the mapping status stays readable next to it so the current
  // state is discoverable without opening an edit flow.
  const correctionItems = useMemo<OverflowMenuItem[]>(() => {
    const entries: OverflowMenuItem[] = []

    if (issueNumber != null) {
      entries.push({
        key: 'fix-issue-number',
        label: 'Fix issue #',
        ariaLabel: 'Fix issue number',
        description: `Set the current issue number for ${threadTitle}`,
        disabled: !activeRatingThread?.id,
        onSelect: () => setIsCorrectionDialogOpen(true),
      })
    }

    if (needsIdentity && issueId) {
      entries.push({
        key: 'find-comicvine-match',
        label: 'Find match',
        ariaLabel: 'Find ComicVine match',
        description: 'Match this issue to a ComicVine series',
        onSelect: () => {
          setSearchMode('confirm')
          setIsSearchDialogOpen(true)
        },
      })
    }

    if (isLinked && issueId) {
      entries.push({
        key: 'wrong-series',
        label: 'Wrong series?',
        ariaLabel: 'Wrong series?',
        description: 'Map this issue to a different series',
        onSelect: () => {
          setSearchMode('replace')
          setIsSearchDialogOpen(true)
        },
      })

      entries.push({
        key: 'remove-comicvine-mapping',
        label: 'Remove ComicVine mapping',
        ariaLabel: 'Remove ComicVine mapping',
        description: 'Unlink the ComicVine mapping from this issue',
        onSelect: async () => {
          if (
            !window.confirm(
              'Are you sure you want to remove the ComicVine mapping from this issue? This will return the issue to the "Not linked" state.',
            )
          ) {
            return
          }
          await comicVineApi.removeIdentity(issueId)
          await fetchIdentity()
          await handleIdentityConfirmed()
        },
      })
    }

    return entries
  }, [
    activeRatingThread?.id,
    isLinked,
    issueId,
    issueNumber,
    needsIdentity,
    threadTitle,
  ])

  const identityStatusLabel = isLinked ? 'Linked' : 'Not linked'

  return (
    <div className="w-full space-y-4">
      {/* Cover rail beside issue identity/details composition. The cover track grows only when
          the outer Roll shell has room for it, so the header can never spill into DecisionCard. */}
      <div className="grid grid-cols-1 lg:grid-cols-[minmax(9rem,11rem)_minmax(0,1fr)] xl:grid-cols-[minmax(10rem,17rem)_minmax(0,1fr)] gap-4 items-start">
        {/* Cover rail */}
        <div className="flex-shrink-0 w-full lg:w-auto">
          <ComicIdentity issueId={issueId} />
        </div>

        {/* Issue identity and details */}
        <div className="min-w-0 space-y-3" data-testid="comic-header-row">
          {/* Provider eyebrow and title block */}
          <div className="space-y-2">
            {identityState?.has_confirmed_identity && identityState.comicvine_issue_id && (
              <div className="text-[10px] font-black uppercase tracking-[0.18em]" style={{ color: 'var(--theme-comic-accent)' }}>
                COMICVINE #{identityState.comicvine_issue_id}
              </div>
            )}
            <div className="flex flex-col gap-2">
              {rollResultLine ? (
                <p
                  data-testid="comic-roll-result"
                  className="text-[11px] font-bold text-[var(--theme-comic-accent)]"
                >
                  {rollResultLine}
                </p>
              ) : null}
              <h2 data-testid="comic-header-title" className="text-xl font-black text-stone-100 leading-tight break-words">
                {threadTitle}
                {issueNumber != null ? <span className="ml-1 text-[var(--theme-comic-accent)]"> #{issueNumber}</span> : null}
              </h2>
              {storyTitle ? (
                <p data-testid="comic-story-title" className="text-sm font-semibold leading-snug text-stone-300 break-words">
                  {storyTitle}
                </p>
              ) : null}
              <p
                data-testid="comic-progress-line"
                className="text-[11px] font-bold text-stone-500"
              >
                {progressItems.map((item, index) => (
                  <span key={item} className="whitespace-nowrap">
                    {index > 0 ? <span aria-hidden="true">{METADATA_SEPARATOR}</span> : null}
                    {item}
                  </span>
                ))}
              </p>
            </div>
          </div>

          {/* Quiet correction affordance: mapping status stays readable and the
              occasional correction actions collapse into one overflow menu
              (issue #3008) instead of competing with the read/rate hierarchy. */}
          {(identityState != null || correctionItems.length > 0) && (
            <div
              className="flex min-w-0 flex-wrap items-center gap-2"
              data-testid="comic-header-controls"
            >
              {identityState != null && (
                <span
                  data-testid="comic-mapping-status"
                  data-mapping-status={isLinked ? 'linked' : 'unlinked'}
                  className={`inline-flex min-h-6 items-center gap-1.5 rounded-full border px-2 py-0.5 text-[10px] font-black uppercase tracking-wider ${
                    isLinked
                      ? 'border-[var(--theme-comic-accent)]/30 text-[var(--theme-comic-accent)]'
                      : 'border-[var(--theme-border)] text-[var(--theme-text-dim)]'
                  }`}
                >
                  <span
                    aria-hidden="true"
                    data-testid="comic-mapping-status-dot"
                    className={`w-1.5 h-1.5 rounded-full ${
                      isLinked ? 'bg-[var(--theme-comic-accent)]' : 'bg-[var(--theme-text-dim)]'
                    }`}
                  />
                  {identityStatusLabel}
                </span>
              )}

              {correctionItems.length > 0 && (
                <OverflowMenu
                  label="Comic corrections"
                  items={correctionItems}
                  triggerTestId="comic-corrections-menu"
                />
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
          onSiblingsMapped={handleSiblingsMapped}
        />
      )}
    </div>
  )
}
