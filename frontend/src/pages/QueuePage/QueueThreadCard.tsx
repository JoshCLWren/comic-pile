import { Link } from 'react-router-dom'
import Tooltip from '../../components/Tooltip'
import { MarqueeTitle } from '../../components/MarqueeTitle'
import PositionMenu from '../../components/PositionMenu'
import { CrossoverTags } from '../../components/CrossoverTags'
import { useCrossoverGroups } from '../../hooks/useCrossoverGroups'
import type { DependencyGroupSummary } from '../../services/api-dependency-groups'
import type { BlockingDependency, Thread } from '../../types'
import QueueThreadActions from './QueueThreadActions'

interface QueueThreadCardProps {
  thread: Thread
  index: number
  isBlocked: boolean
  blockingDependencies: BlockingDependency[]
  crossoverGroups?: DependencyGroupSummary[]
  crossoverGroupsLoading?: boolean
  crossoverGroupsError?: boolean
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
  onOpenThread: () => void
  onSnooze: () => void
  onActionDelete: () => void
  onMoveToFront: () => void
  onMoveToBack: () => void
  onReposition: () => void
  onEdit: () => void
  onDependencies: () => void
  onDelete: () => void
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
  onOpenThread,
  onSnooze,
  onActionDelete,
  onMoveToFront,
  onMoveToBack,
  onReposition,
  onEdit,
  onDependencies,
  onDelete,
}: QueueThreadCardProps) {
  const isMigrated = thread.total_issues !== null
  const blockerLabels = blockingDependencies.map((dependency) => dependency.label)
  const firstBlocker = blockingDependencies[0] ?? null
  const extraBlockerCount = Math.max(blockingDependencies.length - 1, 0)
  const fallbackCrossoverGroups = useCrossoverGroups(
    crossoverGroups === undefined ? [thread.id] : [],
  )
  const resolvedCrossoverGroups = crossoverGroups ?? fallbackCrossoverGroups.groupsByThreadId[thread.id] ?? []
  const resolvedCrossoverGroupsLoading = crossoverGroupsLoading ?? fallbackCrossoverGroups.isPending
  const resolvedCrossoverGroupsError = crossoverGroupsError ?? Boolean(fallbackCrossoverGroups.error)

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
      className={`queue-thread-card group flex flex-col gap-3 px-3 py-3 md:flex-row md:items-center md:gap-4 md:px-4 md:py-3.5 cursor-pointer transition-colors hover:bg-white/[0.04] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)] focus-visible:ring-inset ${isDragOver ? 'bg-amber-500/10' : ''} ${isBlocked ? 'bg-red-500/[0.06]' : ''}`}
      role="link"
      tabIndex={0}
      aria-label={`Open ${thread.title} details`}
      onClick={handleCardClick}
      onKeyDown={handleCardKeyDown}
      onDragOver={onDragOver}
      onDrop={onDrop}
    >
      <div className="flex min-w-0 flex-1 items-start gap-2 md:gap-3">
        <div className="flex shrink-0 items-center gap-1 pt-0.5">
          <Tooltip content="Drag to reorder within the queue.">
            <button
              type="button"
              className="flex h-11 w-11 items-center justify-center rounded-lg text-[var(--theme-text-dim)] hover:bg-white/5 hover:text-[var(--theme-text-muted)] transition-colors text-lg md:h-8 md:w-8"
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
              className="min-w-0 flex-1 text-left"
              onClick={onCardClick}
              aria-label={`Open ${thread.title}`}
              title={thread.title}
            >
              <MarqueeTitle title={thread.title} />
            </button>
            {isBlocked && (
              <Tooltip content={blockerLabels.length > 0 ? blockerLabels.join('\n') : 'Blocked by dependency'}>
                <span className="text-[var(--theme-danger)] text-sm" aria-label="Blocked thread">🔒</span>
              </Tooltip>
            )}
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="text-[11px] font-bold uppercase tracking-widest text-[var(--theme-text-dim)]">
              {thread.format}
            </span>
            {thread.issues_remaining !== null && (
              <span className="text-sm font-medium text-[var(--theme-text-muted)]">
                {isMigrated && !isBlocked && thread.next_unread_issue_number
                  ? `Up next: #${thread.next_unread_issue_number} · ${thread.issues_remaining} remaining`
                  : `${thread.issues_remaining} issues remaining`}
              </span>
            )}
          </div>
          {thread.notes && <p className="mt-1.5 text-xs text-[var(--theme-text-muted)] [overflow-wrap:anywhere] break-words">{thread.notes}</p>}
          <div className="mt-1.5">
            {resolvedCrossoverGroupsLoading ? (
              <p className="text-xs text-[var(--theme-text-dim)]">Loading crossovers…</p>
            ) : resolvedCrossoverGroupsError ? (
              <p className="text-xs text-red-300/80">Crossovers unavailable</p>
            ) : (
              <CrossoverTags groups={resolvedCrossoverGroups} label={`Crossovers for ${thread.title}`} />
            )}
          </div>
          {isBlocked && (
            <div className="mt-2 w-full text-left text-xs text-red-300/80 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">
              {firstBlocker ? (
                <Link
                  to={`/thread/${firstBlocker.thread_id}`}
                  className="font-bold hover:text-red-200 underline decoration-red-400/40"
                  aria-label={`Open ${firstBlocker.thread_title}`}
                  onClick={(event) => event.stopPropagation()}
                >
                  <span aria-hidden="true">🔒 </span>{firstBlocker.label}
                </Link>
              ) : (
                <button
                  type="button"
                  className="font-bold hover:text-red-200 transition-colors"
                  onClick={onDependencies}
                  aria-label={`View dependencies for ${thread.title}`}
                >
                  <span aria-hidden="true">🔒 </span>Blocked by dependency
                </button>
              )}
              {extraBlockerCount > 0 && (
                <button
                  type="button"
                  className="text-red-400/60 ml-1 hover:text-red-300 transition-colors"
                  onClick={onDependencies}
                  aria-label={`View all dependencies for ${thread.title}`}
                >
                  +{extraBlockerCount} more
                </button>
              )}
            </div>
          )}
        </div>
      </div>

      <div className="flex shrink-0 items-center gap-2 self-stretch pl-12 md:pl-0 md:self-center flex-wrap">
<QueueThreadActions
  title={thread.title}
  snoozeIcon={snoozeIcon}
  snoozeLabel={snoozeLabel}
  snoozeDisabled={snoozeDisabled}
  readDisabled={readDisabled}
  readDisabledReason={readDisabledReason}
  isBlocked={isBlocked}
  onRead={onRead}
  onEdit={onOpenThread}
  onSnooze={onSnooze}
  onDelete={onActionDelete}
        />
        <PositionMenu
          thread={thread}
          onMoveToFront={() => onMoveToFront()}
          onReposition={() => onReposition()}
          onMoveToBack={() => onMoveToBack()}
          onEdit={() => onEdit()}
          onDependencies={() => onDependencies()}
          onDelete={() => onDelete()}
        />
      </div>
    </div>
  )
}
