import { useState, useMemo } from 'react'
import IssueCorrectionDialog from '../../../components/IssueCorrectionDialog'
import { ComicIssueIdentity } from '../../../components/ComicIssueCard'
import ComicIssueMappingAction from '../../../components/ComicIssueMappingAction'
import ComicVineSearchDialog from '../../../components/ComicVineSearchDialog'
import QueueMapSeriesDialog from '../../../components/QueueMapSeriesDialog'
import OverflowMenu, { type OverflowMenuItem } from '../../../components/OverflowMenu'
import { getProgressPercentage } from '../utils'
import type { RatingThread } from '../types'
import { ComicIdentity } from './ComicIdentity'
import { TagSection } from '../../../components/Tags/TagSection'
import { useComicVineIssueIntelligence } from '../../../hooks/useComicVineIssueIntelligence'
import { useComicIssueMapping } from '../../../hooks/useComicIssueMapping'

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
  const [isSeriesMappingDialogOpen, setIsSeriesMappingDialogOpen] = useState(false)

  const threadTitle = activeRatingThread?.title ?? 'Loading…'
  const issueNumber = activeRatingThread?.next_issue_number ?? activeRatingThread?.issue_number ?? null
  const issueId = activeRatingThread?.issue_id ?? activeRatingThread?.next_issue_id
  // Shared mapping workflow (#4450): the same hook/component every issue card
  // uses, so Roll no longer owns parallel mapping state. The identity GET is
  // the single current-issue lookup; search runs only when the dialog opens.
  const mapping = useComicIssueMapping({
    issueId: issueId ?? null,
    threadTitle,
    issueNumber,
    onMapped: onRefreshThread,
  })
  const identityState = mapping.identity
  const needsIdentity = mapping.needsIdentity
  const isLinked = mapping.isMapped
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

// Issue #3008: correction tools are occasional recovery actions, so they must
  // not compete with the title, cover, rating, and Mark read & save hierarchy
  // that follows the read/rate flow. They collapse into one quiet overflow
  // trigger. Issue mapping itself is not overflow-only (#4450): the shared
  // ComicIssueMappingAction renders a visible Map/Change action beside the
  // status badge, keeping advanced correction UX working without a parallel
  // mapping behavior.
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
        label: 'Find ComicVine match',
        ariaLabel: 'Find ComicVine match',
        description: 'Match this issue to a ComicVine series',
        onSelect: () => mapping.openMappingDialog('confirm'),
      })
    }

    if (isLinked && issueId) {
      entries.push({
        key: 'wrong-series',
        label: 'Wrong series?',
        ariaLabel: 'Wrong series?',
        description: 'Map this issue to a different series',
        onSelect: () => mapping.openMappingDialog('replace'),
      })
    }

    return entries
  }, [activeRatingThread?.id, issueId, issueNumber, isLinked, mapping, needsIdentity, storyTitle, threadTitle])

  return (
    <div className="w-full space-y-4">
      {/* Cover rail beside issue identity/details composition. The cover track grows only when
          the outer Roll shell has room for it, so the header can never spill into DecisionCard. */}
      <div className="grid grid-cols-1 lg:grid-cols-[minmax(11rem,1fr)_minmax(10rem,1fr)] xl:grid-cols-[minmax(17rem,1fr)_minmax(10rem,1fr)] gap-4 items-start">
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
              <ComicIssueIdentity
                threadTitle={threadTitle}
                issueNumber={issueNumber == null ? '?' : String(issueNumber)}
                status="unread"
                rating={null}
                variant="featured"
                heading
                headingTestId="comic-header-title"
                showStatus={false}
              />
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

          {/* Mapping is a first-class visible action (#4450), not overflow-only.
              Occasional correction actions still collapse into one overflow menu. */}
          {(identityState != null || correctionItems.length > 0) && (
            <div
              className="flex min-w-0 flex-wrap items-center gap-2"
              data-testid="comic-header-controls"
            >
              {issueId != null && (
                <ComicIssueMappingAction
                  issueId={issueId}
                  threadTitle={threadTitle}
                  issueNumber={issueNumber}
                  initialIdentity={identityState}
                  fetchEnabled={false}
                  onMapped={onRefreshThread}
                />
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

      {isSeriesMappingDialogOpen && activeRatingThread && (
        <QueueMapSeriesDialog
          isOpen
          threadId={activeRatingThread.id}
          threadTitle={threadTitle}
          onClose={() => setIsSeriesMappingDialogOpen(false)}
          onMapped={() => { void mapping.fetchIdentity() }}
        />
      )}

      {/* The overflow "Wrong series?" action opens the parent hook's replace
          dialog; the child mapping control owns its own instance, so render
          this one here too. */}
      {mapping.isSearchDialogOpen && issueId && (
        <ComicVineSearchDialog
          isOpen
          issueId={issueId}
          threadTitle={threadTitle}
          issueNumber={issueNumber}
          mode={mapping.searchMode}
          onClose={mapping.closeSearchDialog}
          onConfirmed={mapping.handleIdentityConfirmed}
          onSiblingsMapped={mapping.handleSiblingsMapped}
        />
      )}
    </div>
  )
}
