import { EligibilityExplanation } from '../../components/EligibilityExplanation'
import { ReadingBoundaryExplanation } from '../../components/ReadingBoundaryExplanation'
import type { ReadingBoundaryExplanation as BoundaryExplanation } from '../../services/api-reading-boundaries'
import { Link } from 'react-router-dom'
import { Fragment, useState } from 'react'
import Tooltip from '../../components/Tooltip'
import { MarqueeTitle } from '../../components/MarqueeTitle'
import PositionMenu from '../../components/PositionMenu'
import { CrossoverTags } from '../../components/CrossoverTags'
import { ThreadTagChips } from '../../components/Tags/ThreadTagChips'
import type { DependencyGroupSummary } from '../../services/api-dependency-groups'
import type { BlockingDependency, ThreadListItem } from '../../types'
import QueueThreadActions from './QueueThreadActions'
import QueueMappingHealthIndicator from './QueueMappingHealthIndicator'
import QueueMapSeriesDialog from '../../components/QueueMapSeriesDialog'

interface QueueThreadCardProps {
  thread: ThreadListItem
  index: number
  isBlocked: boolean
  blockingDependencies: BlockingDependency[]
  readingBoundary?: BoundaryExplanation
  boundaryPending?: boolean
  /**
   * Crossover memberships resolved by the owning list view.
   *
   * The card is deliberately presentational: it never fetches. QueuePage owns
   * one batched crossover request for the whole visible thread set and hands the
   * per-thread slice down, because a self-fetching card turns every rendered
   * row into its own request (issue #2979).
   */
  crossoverGroups: DependencyGroupSummary[]
  crossoverGroupsLoading: boolean
  crossoverGroupsError: boolean
  isDragOver: boolean
  snoozeIcon: string
  snoozeLabel: string
  snoozeDisabled: boolean
  readDisabled?: boolean
  readDisabledReason?: string
  onCardClick: () => void
  onDragStart: React.DragEventHandler<HTMLElement>
  onDragEnd: React.DragEventHandler<HTMLElement>
  onDragOver: React.DragEventHandler<HTMLElement>
  onDrop: React.DragEventHandler<HTMLElement>
  onRead: () => void
  onSnooze: () => void
  onMoveToFront: () => void
  onMoveToBack: () => void
  onReposition: () => void
  onEdit: () => void
  onDependencies: () => void
  onDelete: () => void
  onRemoveFromQueue?: () => void
  positionActionsAvailable?: boolean
  sortBy?: 'position' | 'alphabetical' | 'created'
}

type SeriesMetadata = NonNullable<ThreadListItem['series_metadata']>

interface SeriesMetadataPart {
  key: 'year' | 'volume' | 'publisher'
  label: string
  known: boolean
}

/**
 * Build the secondary metadata parts shown under a Queue row title.
 *
 * Verified values render as ordinary muted metadata. A missing year or volume
 * renders a compact truthful fallback so partially mapped series explain what
 * is not known instead of silently omitting a field (#3605). Publisher is
 * omitted when unknown; the issue defines fallback copy only for year/volume.
 */
function seriesMetadataParts(metadata: SeriesMetadata): SeriesMetadataPart[] {
  return [
    {
      key: 'year',
      label: metadata.year != null ? String(metadata.year) : 'Year unknown',
      known: metadata.year != null,
    },
    {
      key: 'volume',
      label: metadata.volume ?? 'Volume unknown',
      known: metadata.volume != null,
    },
    ...(metadata.publisher != null
      ? [{ key: 'publisher' as const, label: metadata.publisher, known: true }]
      : []),
  ]
}

export default function QueueThreadCard({
  thread,
  index,
  isBlocked,
  blockingDependencies,
  readingBoundary,
  boundaryPending,
  crossoverGroups,
  crossoverGroupsLoading,
  crossoverGroupsError,
  isDragOver,
  snoozeIcon,
  snoozeLabel,
  snoozeDisabled,
  readDisabled,
  readDisabledReason,
  onCardClick,
  onDragStart,
  onDragEnd,
  onDragOver,
  onDrop,
  onRead,
  onSnooze,
  onMoveToFront,
  onMoveToBack,
  onReposition,
  onEdit,
  onDependencies,
  onDelete,
  onRemoveFromQueue,
  positionActionsAvailable = true,
  sortBy = 'position',
}: QueueThreadCardProps) {
  // `total_issues` is optional in the generated list item; absent and null
  // both mean the thread has no known issue total.
  const isMigrated = thread.total_issues != null
  const canonicalBlockerLabels =
    readingBoundary?.blockers?.flatMap((blocker) => blocker.waiting_on?.map((issue) => issue.label) ?? []) ?? []
  // Default deployments get no canonical blockers, so the lock tooltip keeps
  // naming the legacy batch's requirements instead of falling back to generic
  // copy (#4025).
  const blockerLabels =
    canonicalBlockerLabels.length > 0
      ? canonicalBlockerLabels
      : blockingDependencies.map((dependency) => dependency.label)

  // Interactive controls inside a Queue card must not open Thread Detail.
  const isInteractiveTarget = (target: EventTarget | null, card: HTMLDivElement) => {
    const interactive = target instanceof Element
      ? target.closest('button, a, input, select, textarea, summary, [role="button"], [role="link"]')
      : null
    return interactive !== null && interactive !== card
  }

  const handleCardClick = (event: React.MouseEvent<HTMLDivElement>) => {
    if (isInteractiveTarget(event.target, event.currentTarget)) {
      return
    }
    onCardClick()
  }

  const handleCardKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.target !== event.currentTarget || (event.key !== 'Enter' && event.key !== ' ')) {
      return
    }
    event.preventDefault()
    onCardClick()
  }

  const [repairOpen, setRepairOpen] = useState(false)

  const handleRepairMapped = () => {
    setRepairOpen(false)
    // Queue pages refresh through the shared series-mapping commit hook, so the
    // mapping indicator updates without a hard reload or a manual refetch here.
  }

  return (
    <>
    <div
      data-testid="queue-thread-item"
      className={`queue-thread-card group relative flex flex-col gap-3 px-3 py-3 @2xl:flex-row @2xl:items-center @2xl:gap-4 @2xl:px-4 @2xl:py-3.5 cursor-pointer transition-colors hover:bg-white/[0.04] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)] focus-visible:ring-inset`}
      role="link"
      tabIndex={0}
      aria-label={`Open ${thread.title} details`}
      onClick={handleCardClick}
      onKeyDown={handleCardKeyDown}
      onDragOver={onDragOver}
      onDrop={onDrop}
    >
      {isDragOver && (
        <div
          data-testid="queue-thread-drag-over"
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 bg-amber-500/10"
        />
      )}
      <div className="relative flex min-w-0 flex-1 items-start gap-2 @2xl:gap-3">
        <div className="flex shrink-0 items-center gap-1 pt-0.5">
          {positionActionsAvailable && sortBy === 'position' && (
            <Tooltip content="Drag to reorder within the queue.">
              <button
                type="button"
                className="flex h-11 w-11 items-center justify-center rounded-lg text-[var(--theme-text-dim)] hover:bg-white/5 hover:text-[var(--theme-text-muted)] transition-colors text-lg @2xl:h-8 @2xl:w-8"
                draggable
                onDragStart={onDragStart}
                onDragEnd={onDragEnd}
                aria-label="Drag to reorder"
              >
                ⠿
              </button>
            </Tooltip>
          )}
          <span className="w-6 text-right text-xs font-bold tabular-nums text-[var(--theme-text-dim)]">
            #{thread.queue_position ?? index + 1}
          </span>
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 items-center gap-2">
            <button
              type="button"
              className="min-w-24 flex-1 text-left"
              onClick={onCardClick}
              aria-label={`Open ${thread.title}`}
              title={thread.title}
            >
              <MarqueeTitle title={thread.title} />
            </button>
            {isBlocked && (
              <Tooltip content={blockerLabels[0] ?? 'Waiting for reading requirements'}>
                <span className="text-[var(--theme-continuity-accent)] text-sm" aria-label="Blocked series">🔒</span>
              </Tooltip>
            )}
          </div>
          <div
            className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1"
            data-testid="queue-series-metadata"
          >
            {thread.series_metadata != null ? (
              <>
                <span className="sr-only">Series metadata: </span>
                {thread.series_metadata.year == null &&
                thread.series_metadata.volume == null &&
                thread.series_metadata.publisher == null ? (
                  <span className="text-xs text-[var(--theme-text-dim)]">
                    No confirmed metadata
                  </span>
                ) : (
                  seriesMetadataParts(thread.series_metadata).map((part, partIndex) => (
                    <Fragment key={part.key}>
                      {partIndex > 0 && (
                        <span
                          className="text-xs text-[var(--theme-text-muted)]"
                          aria-hidden="true"
                        >
                          {' · '}
                        </span>
                      )}
                      <span
                        className={
                          part.known
                            ? 'text-xs text-[var(--theme-text-muted)]'
                            : 'text-xs text-[var(--theme-text-dim)]'
                        }
                      >
                        {part.label}
                      </span>
                    </Fragment>
                  ))
                )}
              </>
            ) : (
              <span className="text-xs text-[var(--theme-text-dim)]" data-testid="series-unmapped">
                Unmapped series
              </span>
            )}
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="text-[11px] font-bold uppercase tracking-widest text-[var(--theme-text-dim)]">
              {thread.format}
            </span>
            {thread.comicvine_mapping != null && (
              <QueueMappingHealthIndicator
                mapping={thread.comicvine_mapping}
                onMapSeries={() => setRepairOpen(true)}
              />
            )}
            {thread.issues_remaining !== null && (
              <span className="text-sm font-medium text-[var(--theme-text-muted)]">
                {isMigrated && !isBlocked && thread.next_unread_issue_number
                  ? `Up next: #${thread.next_unread_issue_number} · ${thread.issues_remaining} issue${thread.issues_remaining === 1 ? '' : 's'} remaining`
                  : `${thread.issues_remaining} issue${thread.issues_remaining === 1 ? '' : 's'} remaining`}
              </span>
            )}
          </div>
          <ThreadTagChips
            tags={thread.tags}
            label={`Tags for ${thread.title}`}
            className="mt-1.5"
          />
          {thread.notes && <p className="mt-1.5 text-xs text-[var(--theme-text-muted)] [overflow-wrap:anywhere] break-words">{thread.notes}</p>}
          <div className="mt-1.5">
            {crossoverGroupsLoading ? (
              <p className="text-xs text-[var(--theme-text-dim)]">Loading crossovers…</p>
            ) : crossoverGroupsError ? (
              <p className="text-xs text-red-300/80">Crossovers unavailable</p>
            ) : (
              <CrossoverTags groups={crossoverGroups} label={`Crossovers for ${thread.title}`} />
            )}
          </div>
          {isBlocked && (
            <div
              data-testid="queue-thread-blocked-detail"
              className="mt-2 w-full rounded-lg border border-[var(--theme-continuity-accent)]/20 bg-[var(--theme-continuity-accent)]/10 px-3 py-2 text-left text-xs text-[var(--theme-text-muted)]"
            >
              <ReadingBoundaryExplanation
                compact
                explanation={readingBoundary}
                isPending={boundaryPending}
                fallback={
                  <>
                    {blockingDependencies[0] ? (
                      <p>
                        Read <Link
                          to={`/thread/${blockingDependencies[0].thread_id}`}
                          aria-label={`Read required issue: ${blockingDependencies[0].label}`}
                          className="text-[var(--theme-continuity-accent)] underline"
                        >{blockingDependencies[0].label}</Link> first.
                      </p>
                    ) : <p>{thread.blocking_reasons?.[0] ?? 'Waiting for reading requirements'}</p>}
                    <details className="mt-1">
                      <summary className="cursor-pointer font-semibold">Show all reading requirements</summary>
                      <EligibilityExplanation
                        isBlocked={isBlocked}
                        reasons={thread.blocking_reasons}
                        dependencies={blockingDependencies}
                      />
                    </details>
                    <button
                      type="button"
                      onClick={onDependencies}
                      aria-label={`View dependencies for ${thread.title}`}
                      className="min-h-11 text-sm font-semibold text-[var(--theme-continuity-accent)]"
                    >
                      Manage prerequisites
                    </button>
                  </>
                }
              />
              {isBlocked && <p className="mt-1 text-[var(--theme-text-dim)]">Read &amp; Rate unlocks once the active reading requirements are satisfied.</p>}
            </div>
          )}
        </div>
      </div>

      <div className="flex shrink-0 items-center gap-2 self-stretch pl-12 @2xl:pl-0 @2xl:self-center flex-wrap">
        <QueueThreadActions
          title={thread.title}
          readDisabled={readDisabled}
          readDisabledReason={readDisabledReason}
          onRead={onRead}
        />
        <PositionMenu
          thread={thread}
          onMoveToFront={() => onMoveToFront()}
          onReposition={() => onReposition()}
          onMoveToBack={() => onMoveToBack()}
          onEdit={() => onEdit()}
          onDependencies={() => onDependencies()}
          onDelete={() => onDelete()}
          onRemoveFromQueue={onRemoveFromQueue}
          positionActionsAvailable={positionActionsAvailable}
          snoozeIcon={snoozeIcon}
          snoozeLabel={snoozeLabel}
          snoozeDisabled={snoozeDisabled}
          onSnooze={onSnooze}
          sortBy={sortBy}
        />
      </div>
    </div>
    <QueueMapSeriesDialog
      isOpen={repairOpen}
      threadId={thread.id}
      threadTitle={thread.title}
      onClose={() => setRepairOpen(false)}
      onMapped={handleRepairMapped}
    />
    </>
  )
}
