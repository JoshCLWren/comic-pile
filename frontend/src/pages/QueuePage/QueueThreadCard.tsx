import Tooltip from '../../components/Tooltip'
import { MarqueeTitle } from '../../components/MarqueeTitle'
import PositionMenu from '../../components/PositionMenu'
import Swipeable from '../../components/Swipeable'
import { CollectionBadge } from './CollectionBadge'
import type { Thread } from '../../types'

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
  onSwipeRead: () => void
  onSwipeEdit: () => void
  onSwipeSnooze: () => void
  onSwipeDelete: () => void
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
  onSwipeRead,
  onSwipeEdit,
  onSwipeSnooze,
  onSwipeDelete,
  onMoveToFront,
  onMoveToBack,
  onReposition,
  onEdit,
  onDependencies,
  onDelete,
}: QueueThreadCardProps) {
  const isMigrated = thread.total_issues !== null

  return (
    <Swipeable
      data-testid="queue-thread-item"
      onCardClick={onCardClick}
      className="rounded-xl"
      actions={[
        { icon: '📖', label: 'Read', onClick: onSwipeRead, color: 'bg-amber-600/30 text-amber-300' },
        { icon: '✏️', label: 'Edit', onClick: onSwipeEdit, color: 'bg-white/10 text-stone-300' },
        { icon: snoozeIcon, label: snoozeLabel, onClick: onSwipeSnooze, color: 'bg-teal-600/20 text-teal-400' },
        { icon: '🗑', label: 'Delete', onClick: onSwipeDelete, color: 'bg-red-600/25 text-red-400' },
      ]}
    >
      <div
        className={`glass-card p-3 md:p-4 space-y-2 md:space-y-3 group transition-all hover:border-white/20 ${isDragOver ? 'border-amber-400/60' : ''} ${isBlocked ? 'border-red-400/30 bg-red-500/5' : ''}`}
        onDragOver={onDragOver}
        onDrop={onDrop}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            onCardClick()
          }
        }}
      >
        <div className="flex justify-between items-start gap-2 md:gap-3">
          <div className="flex items-start gap-2 md:gap-3 min-w-0 flex-1">
            <span className="text-xl md:text-2xl font-black text-amber-600/30">
              #{index + 1}
            </span>
            <div className="flex items-center gap-2 min-w-0 flex-1">
              <Tooltip content="Drag to reorder within the queue.">
                <button
                  type="button"
                  className="text-stone-500 hover:text-stone-300 transition-colors text-lg"
                  draggable
                  onDragStart={onDragStart}
                  onDragEnd={onDragEnd}
                  aria-label="Drag to reorder"
                  onClick={(e) => e.stopPropagation()}
                >
                  ⠿
                </button>
              </Tooltip>
              <MarqueeTitle title={thread.title} />
              {isBlocked && (
                <Tooltip content={blockingReasons.length > 0 ? blockingReasons.join('\n') : 'Blocked by dependency'}>
                  <span className="text-red-300 text-lg" aria-label="Blocked thread">🔒</span>
                </Tooltip>
              )}
            </div>
          </div>
          <div className="hidden md:flex items-center gap-1">
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
          <div className="md:hidden flex items-center gap-1">
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation()
                onDependencies()
              }}
              className="flex items-center justify-center w-11 h-11 text-amber-400/70 hover:text-amber-300 transition-colors text-lg rounded-lg hover:bg-white/5 focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-500"
              aria-label="Manage dependencies"
              aria-haspopup="dialog"
              data-testid="mobile-dependency-action"
            >
              &#x26D3;
            </button>
          </div>
        </div>
        <div className="pl-8 md:pl-[2.75rem]">
          <p className="text-xs text-stone-500 uppercase tracking-widest font-bold">{thread.format}</p>
          {thread.collection_id && (
            <div className="mt-1.5 flex">
              <CollectionBadge collectionId={thread.collection_id} />
            </div>
          )}
          {thread.notes && <p className="text-xs text-stone-400 mt-2">{thread.notes}</p>}
          {thread.issues_remaining !== null && (
            <p className="text-sm text-stone-300 mt-2 font-medium">
              {isMigrated && thread.next_unread_issue_number
                ? `Up next: #${thread.next_unread_issue_number} · ${thread.issues_remaining} remaining`
                : `${thread.issues_remaining} issues remaining`
              }
            </p>
          )}
          {isBlocked && blockingReasons.length > 0 && (
            <button
              type="button"
              className="mt-2 w-full text-left text-xs text-red-300/80 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2 hover:bg-red-500/15 transition-colors"
              onClick={(e) => {
                e.stopPropagation()
                onDependencies()
              }}
              aria-label={`View dependencies for ${thread.title}`}
            >
              <span className="font-bold">🔒 {blockingReasons[0]}</span>
              {blockingReasons.length > 1 && (
                <span className="text-red-400/60 ml-1">+{blockingReasons.length - 1} more</span>
              )}
            </button>
          )}
        </div>
      </div>
    </Swipeable>
  )
}
