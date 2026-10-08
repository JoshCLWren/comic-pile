import { Link } from 'react-router-dom'
import Tooltip from '../../components/Tooltip'
import { MarqueeTitle } from '../../components/MarqueeTitle'
import PositionMenu from '../../components/PositionMenu'
import { CrossoverTags } from '../../components/CrossoverTags'
import type { DependencyGroupSummary } from '../../services/api-dependency-groups'
import type { BlockingDependency, ThreadListItem } from '../../types'
import QueueThreadActions from './QueueThreadActions'

export interface ComicVineMappingHealth {
  /**
   * Compact ComicVine mapping-health projection for a queue row.
   *
   * Mirrors the server `ComicVineMappingHealth` contract from #2776:
   * `fully_mapped` and `not_applicable` stay quiet, while `partial`,
   * `unresolved`, and `needs_review` surface the repair action. The
   * generated OpenAPI client predates that projection, so the card declares
   * the contract locally rather than reading it off `ThreadListItem`.
   */
  status: 'fully_mapped' | 'partial' | 'unresolved' | 'needs_review' | 'not_applicable'
  tracked_issue_count: number
  confirmed_issue_count: number
  needs_mapping_count: number
  needs_review_count: number
}

export type ThreadWithMapping = ThreadListItem & {
  comicvine_mapping?: ComicVineMappingHealth | null
}

interface QueueThreadCardProps {
  thread: ThreadWithMapping
  index: number
  isBlocked: boolean
  blockingDependencies: BlockingDependency[]
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
  onMapSeries: () => void
}

export default function QueueThreadCard({
  thread,
  index,
  isBlocked,
  blockingDependencies,
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
  onMapSeries,
}: QueueThreadCardProps) {
  const mapping = thread.comicvine_mapping ?? null
  const showMappingAction =
    mapping !== null && mapping.status !== 'fully_mapped' && mapping.status !== 'not_applicable'
  // Ambiguous/conflicting identities stay visually distinct from ordinary
  // missing mappings: either an explicit review status or a partial row that
  // still carries review-count rows reports "Review needed".
  const mappingNeedsReview =
    showMappingAction &&
    mapping !== null &&
    (mapping.status === 'needs_review' || mapping.needs_review_count > 0)
  const mappingCount = mapping?.needs_mapping_count ?? 0
  const mappingLabel =
    mapping !== null && mappingNeedsReview
      ? 'Review needed'
      : `${mappingCount} issue${mappingCount === 1 ? '' : 's'} need mapping`
  const mappingAccessibleName = `Repair ComicVine mapping for ${thread.title}: ${mappingLabel}`

  // `total_issues` is optional in the generated list item; absent and null
  // both mean the thread has no known issue total.
  const isMigrated = thread.total_issues != null
  const blockerLabels = blockingDependencies.map((dependency) => dependency.label)
  const firstBlocker = blockingDependencies[0] ?? null
  const extraBlockerCount = Math.max(blockingDependencies.length - 1, 0)

  const isInteractiveTarget = (target: EventTarget | null, card: HTMLDivElement) => {
    const interactive = target instanceof Element
      ? target.closest('button, a, input, select, textarea, [role="button"], [role="link"]')
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

  return (
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
          <span className="w-6 text-right text-xs font-bold tabular-nums text-[var(--theme-text-dim)]">
            #{index + 1}
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
              <Tooltip content={blockerLabels.length > 0 ? blockerLabels.join('\n') : 'Blocked by dependency'}>
                <span className="text-[var(--theme-continuity-accent)] text-sm" aria-label="Blocked series">🔒</span>
              </Tooltip>
            )}
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="text-[11px] font-bold uppercase tracking-widest text-[var(--theme-text-dim)]">
              {thread.format}
            </span>
            {showMappingAction && (
              <button
                type="button"
                onClick={(event) => {
                  event.stopPropagation()
                  onMapSeries()
                }}
                className="flex items-center gap-1 px-1.5 py-0.5 rounded-full bg-[var(--theme-warning)]/10 border border-[var(--theme-warning)]/20 hover:bg-[var(--theme-warning)]/20 transition-colors group"
                title={mappingAccessibleName}
                aria-label={mappingAccessibleName}
              >
                <span className="text-[var(--theme-warning)] text-[10px] group-hover:scale-110 transition-transform" aria-hidden="true">⚠️</span>
                <span className="text-[10px] font-bold uppercase tracking-wider text-[var(--theme-warning)]/80 group-hover:text-[var(--theme-warning)] transition-colors">
                  {mappingLabel}
                </span>
              </button>
            )}
            {thread.issues_remaining !== null && (
              <span className="text-sm font-medium text-[var(--theme-text-muted)]">
                {isMigrated && !isBlocked && thread.next_unread_issue_number
                  ? `Up next: #${thread.next_unread_issue_number} · ${thread.issues_remaining} issue${thread.issues_remaining === 1 ? '' : 's'} remaining`
                  : `${thread.issues_remaining} issue${thread.issues_remaining === 1 ? '' : 's'} remaining`}
              </span>
            )}
          </div>
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
              {firstBlocker ? (
                <Link
                  to={`/thread/${firstBlocker.thread_id}`}
                  className="font-bold text-[var(--theme-continuity-accent)] underline decoration-[var(--theme-continuity-accent)]/40 hover:text-[var(--theme-text-primary)]"
                  aria-label={`Open ${firstBlocker.thread_title}`}
                  onClick={(event) => event.stopPropagation()}
                >
                  <span aria-hidden="true">🔒 </span>{firstBlocker.label}
                </Link>
              ) : (
                <button
                  type="button"
                  className="font-bold text-[var(--theme-continuity-accent)] transition-colors hover:text-[var(--theme-text-primary)]"
                  onClick={onDependencies}
                  aria-label={`View dependencies for ${thread.title}`}
                >
                  <span aria-hidden="true">🔒 </span>Blocked by dependency
                </button>
              )}
              {extraBlockerCount > 0 && (
                <button
                  type="button"
                  className="ml-1 text-[var(--theme-text-dim)] transition-colors hover:text-[var(--theme-continuity-accent)]"
                  onClick={onDependencies}
                  aria-label={`View all dependencies for ${thread.title}`}
                >
                  +{extraBlockerCount} more
                </button>
              )}
              <p className="mt-1.5 text-[var(--theme-text-dim)]">
                Secondary actions are in the menu. Read & Rate unlocks once the
                blocker{extraBlockerCount > 0 ? 's' : ''} above{' '}
                {extraBlockerCount > 0 ? 'are' : 'is'} cleared.
              </p>
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
          snoozeIcon={snoozeIcon}
          snoozeLabel={snoozeLabel}
          snoozeDisabled={snoozeDisabled}
          onSnooze={onSnooze}
        />
      </div>
    </div>
  )
}
