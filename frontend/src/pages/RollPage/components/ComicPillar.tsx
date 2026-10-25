import { useState, useEffect, useCallback, useMemo } from 'react'
import IssueCorrectionDialog from '../../../components/IssueCorrectionDialog'
import ComicVineSearchDialog from '../../../components/ComicVineSearchDialog'
import QueueMapSeriesDialog from '../../../components/QueueMapSeriesDialog'
import Modal from '../../../components/Modal'
import OverflowMenu, { type OverflowMenuItem } from '../../../components/OverflowMenu'
import { comicVineApi } from '../../../services/api-comicvine'
import type { ComicVineIssueCandidate } from '../../../services/api-comicvine'
import type { IssueIdentityResponse } from '../../../services/api-comicvine'
import { getProgressPercentage } from '../utils'
import type { RatingThread } from '../types'
import { ComicIdentity } from './ComicIdentity'
import { TagSection } from '../../../components/Tags/TagSection'
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
  const [isSeriesMappingDialogOpen, setIsSeriesMappingDialogOpen] = useState(false)
  const [isRemoveMappingDialogOpen, setIsRemoveMappingDialogOpen] = useState(false)
  const [isRemovingMapping, setIsRemovingMapping] = useState(false)
  const [removeMappingError, setRemoveMappingError] = useState<string | null>(null)
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
  // Read counts cannot identify an issue's ordinal when later issues are read.
  // Keep the canonical number until the actual tracked position is available.
  // The publication date is rendered once, beside the cover in ComicIdentity.
  // Repeating it here only produced two dates for the same issue.
  const progressItems = [
    ...(issueNumber != null && totalIssues != null
      ? [`Issue #${issueNumber}`]
      : []),
    `${progress}% complete`,
    `${issuesRemaining} left`,
  ]

  // Issue #3126: the result card must name the face the roll actually produced,
  // otherwise the face-mapping list is the only cross-reference a reader has for
  // why this series was picked. Both facts are thread-scoped: the die face is the
  // roll that selected this thread, and queue position is 1-based, with 0 meaning
  // the payload carried no position rather than "first".
  //
  // Manual picks write a tombstone roll with result 0 (see
  // `set_pending_thread`), so reporting "Rolled 0 of d6" invented a die result
  // that never happened (#3450). Result 0 is reserved for "picked manually".
  const rolledFace = activeRatingThread?.last_rolled_result ?? null
  const queuePosition = activeRatingThread?.queue_position ?? 0
  const rollResultLine =
    rolledFace === 0
      ? `Picked manually${queuePosition > 0 ? ` · #${queuePosition} in queue` : ''}`
      : rolledFace != null && currentDie != null
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

  const handleRemoveMapping = useCallback(async () => {
    if (!issueId) return
    setRemoveMappingError(null)
    setIsRemovingMapping(true)
    try {
      await comicVineApi.removeIdentity(issueId)
      setIsRemoveMappingDialogOpen(false)
      await fetchIdentity()
      await handleIdentityConfirmed()
    } catch (error) {
      setRemoveMappingError(
        error instanceof Error ? error.message : 'Could not remove the ComicVine mapping.',
      )
    } finally {
      setIsRemovingMapping(false)
    }
  }, [fetchIdentity, handleIdentityConfirmed, issueId])

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

    // Show "Map series" for issues whose series still lack details (missing story title)
    const seriesIsComplete = storyTitle != null
    if (activeRatingThread?.id && issueId && !seriesIsComplete) {
      entries.push({
        key: 'map-series',
        label: 'Map series',
        ariaLabel: 'Map series',
        description: 'Check this series and update missing ComicVine details',
        onSelect: () => setIsSeriesMappingDialogOpen(true),
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
        onSelect: () => {
          // Issue #3451: use the app's accessible dialog instead of a native
          // `window.confirm`, which froze the page and ignored the app's focus
          // and theme contracts.
          setRemoveMappingError(null)
          setIsRemoveMappingDialogOpen(true)
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
    storyTitle,
    threadTitle,
    fetchIdentity,
    handleIdentityConfirmed,
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

          {/* Inline tag editing for the currently rolled issue (issue #3032):
              content-sized and wrapping so the controls never destabilize the
              Roll layout at any viewport. */}
          {issueId != null && activeRatingThread != null && (
            <div className="min-w-0" data-testid="rolled-issue-tags">
              <TagSection
                targetType="Issue"
                targetId={issueId}
                targetLabel={
                  issueNumber != null
                    ? `${threadTitle} #${issueNumber}`
                    : threadTitle
                }
              />
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
      {isSeriesMappingDialogOpen && activeRatingThread && (
        <QueueMapSeriesDialog
          isOpen
          threadId={activeRatingThread.id}
          threadTitle={threadTitle}
          onClose={() => setIsSeriesMappingDialogOpen(false)}
          onMapped={() => { void fetchIdentity() }}
        />
      )}
      <Modal
        isOpen={isRemoveMappingDialogOpen}
        title="Remove ComicVine mapping?"
        onClose={() => {
          if (!isRemovingMapping) setIsRemoveMappingDialogOpen(false)
        }}
        data-testid="remove-comicvine-mapping-dialog"
      >
        <div className="space-y-4">
          <p className="text-sm text-[var(--theme-text-muted)]">
            This returns {issueNumber ? `issue #${issueNumber}` : 'this issue'} to the
            &quot;Not linked&quot; state. You can map it again later.
          </p>
          {removeMappingError && (
            <p role="alert" className="text-sm text-[var(--theme-danger)]">
              {removeMappingError}
            </p>
          )}
          <div className="flex flex-col-reverse sm:flex-row gap-2 sm:justify-end">
            <button
              type="button"
              onClick={() => setIsRemoveMappingDialogOpen(false)}
              disabled={isRemovingMapping}
              className="min-h-11 sm:min-h-9 rounded-lg border border-[var(--theme-border)] px-4 py-2 text-xs font-bold text-[var(--theme-text-muted)] hover:text-[var(--theme-text-primary)] transition-colors disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={() => void handleRemoveMapping()}
              disabled={isRemovingMapping}
              className="min-h-11 sm:min-h-9 rounded-lg bg-[var(--theme-danger)] px-4 py-2 text-xs font-black text-white hover:bg-[var(--theme-danger-hover)] transition-colors disabled:opacity-50"
            >
              {isRemovingMapping ? 'Removing…' : 'Remove mapping'}
            </button>
          </div>
        </div>
      </Modal>
    </div>
  )
}
