import Tooltip from '../../components/Tooltip'
import { MarqueeTitle } from '../../components/MarqueeTitle'
import PositionMenu from '../../components/PositionMenu'
import type { Thread } from '../../types'
import QueueThreadActions from './QueueThreadActions'

interface QueueThreadCardProps {
  thread: Thread
  index: number
  isBlocked: boolean
  blockingReasons: string[]
  isDragOver: boolean
  snoozeIcon: string
  snoozeLabel: string
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
  blockingReasons,
  isDragOver,
  snoozeIcon,
  snoozeLabel,
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

  return (
    <div
      data-testid="queue-thread-item"
      className={`queue-thread-card glass-card h-full p-3 md:p-4 space-y-2 md:space-y-3 group transition-all hover:border-white/20 ${isDragOver ? 'border-amber-400/60' : ''} ${isBlocked ? 'border-red-400/30 bg-red-500/5' : ''}`}
      onDragOver={onDragOver}
      onDrop={onDrop}
    >
      <div className="flex justify-between items-start gap-2 md:gap-3">
        <div className="flex items-start gap-2 md:gap-3 min-w-0 flex-1">
          <span className="text-xl md:text-2xl font-black text-amber-600/30">#{index + 1}</span>
          <div className="flex items-center gap-2 min-w-0 flex-1">
            <Tooltip content="Drag to reorder within the queue.">
              <button
                type="button"
                className="text-stone-500 hover:text-stone-300 transition-colors text-lg"
                draggable
                onDragStart={onDragStart}
                onDragEnd={onDragEnd}
                aria-label="Drag to reorder"
              >
                ⠿
              </button>
            </Tooltip>
            <button
              type="button"
              className="min-w-0 flex-1 text-left"
              onClick={onCardClick}
              aria-label={`Open ${thread.title}`}
            >
              <MarqueeTitle title={thread.title} />
            </button>
            {isBlocked && (
              <Tooltip content={blockingReasons.length > 0 ? blockingReasons.join('\n') : 'Blocked by dependency'}>
                <span className="text-red-300 text-lg" aria-label="Blocked thread">🔒</span>
              </Tooltip>
            )}
          </div>
        </div>
        <div className="flex items-center gap-1">
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

      <div className="pl-8 md:pl-[2.75rem]">
        <p className="text-xs text-stone-500 uppercase tracking-widest font-bold">{thread.format}</p>
        {thread.notes && <p className="text-xs text-stone-400 mt-2">{thread.notes}</p>}
        {thread.issues_remaining !== null && (
          <p className="text-sm text-stone-300 mt-2 font-medium">
            {isMigrated && thread.next_unread_issue_number
              ? `Up next: #${thread.next_unread_issue_number} · ${thread.issues_remaining} remaining`
              : `${thread.issues_remaining} issues remaining`}
          </p>
        )}
        {isBlocked && blockingReasons.length > 0 && (
          <button
            type="button"
            className="mt-2 w-full text-left text-xs text-red-300/80 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2 hover:bg-red-500/15 transition-colors"
            onClick={onDependencies}
            aria-label={`View dependencies for ${thread.title}`}
          >
            <span className="font-bold">🔒 {blockingReasons[0]}</span>
            {blockingReasons.length > 1 && <span className="text-red-400/60 ml-1">+{blockingReasons.length - 1} more</span>}
          </button>
        )}
      </div>

      <QueueThreadActions
        title={thread.title}
        snoozeIcon={snoozeIcon}
        snoozeLabel={snoozeLabel}
        onRead={onRead}
        onEdit={onOpenThread}
        onSnooze={onSnooze}
        onDelete={onActionDelete}
      />
    </div>
  )
}
