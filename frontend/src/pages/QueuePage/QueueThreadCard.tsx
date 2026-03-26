import type { DragEvent } from 'react'
import Tooltip from '../../components/Tooltip'
import { CollectionBadge } from './CollectionBadge'
import type { Thread } from '../../types'

interface QueueThreadCardProps {
  thread: Thread
  blockingReasons: string[]
  isBlocked: boolean
  isBlockedSection: boolean
  isDragOver: boolean
  dragEnabled: boolean
  onSelect: () => void
  onDragOver?: (event: DragEvent<HTMLElement>) => void
  onDrop?: (event: DragEvent<HTMLElement>) => void
  onDragStart?: (event: DragEvent<HTMLElement>) => void
  onDragEnd?: (event: DragEvent<HTMLElement>) => void
  onEdit: () => void
  onManageDependencies: () => void
  onDelete: () => void
  onMoveFront: () => void
  onMoveBack: () => void
  onReposition: () => void
}

export function QueueThreadCard({
  thread,
  blockingReasons,
  isBlocked,
  isBlockedSection,
  isDragOver,
  dragEnabled,
  onSelect,
  onDragOver,
  onDrop,
  onDragStart,
  onDragEnd,
  onEdit,
  onManageDependencies,
  onDelete,
  onMoveFront,
  onMoveBack,
  onReposition,
}: QueueThreadCardProps) {
  const isMigrated = thread.total_issues !== null

  const cardClasses = [
    'glass-card p-4 space-y-3 group transition-all cursor-pointer',
    isBlockedSection
      ? 'bg-stone-900/50 border-white/5 text-stone-200/80 backdrop-saturate-75 hover:border-white/15'
      : 'hover:border-white/20',
    isBlocked ? 'border-red-400/30 bg-red-500/5' : '',
    isDragOver && dragEnabled ? 'border-amber-400/60' : '',
  ]
    .filter(Boolean)
    .join(' ')

  const dragHandleClasses = [
    'text-lg transition-colors',
    dragEnabled ? 'text-stone-500 hover:text-stone-300 cursor-grab' : 'text-stone-700/70 cursor-not-allowed',
  ].join(' ')

  return (
    <div
      data-testid="queue-thread-item"
      className={cardClasses}
      onDragOver={dragEnabled ? onDragOver : undefined}
      onDrop={dragEnabled ? onDrop : undefined}
      onClick={onSelect}
      role="button"
      tabIndex={0}
      aria-label={`${isBlockedSection ? 'Blocked' : 'Active'} thread ${thread.title}`}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault()
          onSelect()
        }
      }}
    >
      <div className="flex justify-between items-start gap-3">
        <div className="flex items-start gap-3 min-w-0 flex-1">
          <span className="text-2xl font-black text-amber-600/40">#{thread.queue_position}</span>
          <div className="flex items-center gap-2 min-w-0 flex-1">
            <Tooltip content={dragEnabled ? 'Drag to reorder within the queue.' : 'Expand blocked threads to reorder.'}>
              <button
                type="button"
                className={dragHandleClasses}
                draggable={dragEnabled}
                onDragStart={dragEnabled ? onDragStart : undefined}
                onDragEnd={dragEnabled ? onDragEnd : undefined}
                aria-label="Drag to reorder"
                aria-disabled={!dragEnabled}
                onClick={(event) => event.stopPropagation()}
              >
                ⠿
              </button>
            </Tooltip>
            <h3 className={`text-lg font-bold flex-1 line-clamp-2 ${isBlockedSection ? 'text-stone-200' : 'text-white'}`}>
              {thread.title}
            </h3>
            {isBlocked && (
              <Tooltip content={blockingReasons.length > 0 ? blockingReasons.join('\n') : 'Blocked by dependency'}>
                <span className="text-red-300 text-lg" aria-label="Blocked thread">🔒</span>
              </Tooltip>
            )}
          </div>
        </div>
        <div className="hidden md:flex items-center gap-2">
          <Tooltip content="Edit thread details.">
            <button
              type="button"
              onClick={(event) => {
                event.stopPropagation()
                onEdit()
              }}
              className="text-stone-500 hover:text-white transition-colors text-sm"
              aria-label="Edit thread"
            >
              ✎
            </button>
          </Tooltip>
          <Tooltip content="Manage dependencies for this thread.">
            <button
              type="button"
              onClick={(event) => {
                event.stopPropagation()
                onManageDependencies()
              }}
              className="text-stone-500 hover:text-white transition-colors text-sm"
              aria-label="Manage dependencies"
            >
              🔗
            </button>
          </Tooltip>
          <Tooltip content="Delete thread from queue.">
            <button
              type="button"
              onClick={(event) => {
                event.stopPropagation()
                onDelete()
              }}
              className="text-stone-500 hover:text-red-400 transition-colors text-xl"
              aria-label="Delete thread"
            >
              &times;
            </button>
          </Tooltip>
        </div>
        <div className="md:hidden text-stone-500 flex items-center justify-center w-8 h-8 text-xl">
          ⋮
        </div>
      </div>
      <div className="pl-[2.75rem]">
        <p className="text-xs text-stone-500 uppercase tracking-widest font-bold">{thread.format}</p>
        {thread.collection_id && (
          <div className="mt-1.5 flex">
            <CollectionBadge collectionId={thread.collection_id} />
          </div>
        )}
        {thread.notes && <p className="text-xs text-stone-400 mt-2">{thread.notes}</p>}
        {thread.issues_remaining !== null && (
          <p className={`text-sm mt-2 font-medium ${isBlockedSection ? 'text-stone-300/90' : 'text-stone-300'}`}>
            {isMigrated && thread.next_unread_issue_number
              ? `On #${thread.next_unread_issue_number} · ${thread.issues_remaining} remaining`
              : `${thread.issues_remaining} issues remaining`
            }
          </p>
        )}
        {isBlocked && blockingReasons.length > 0 && (
          <button
            type="button"
            className="mt-2 w-full text-left text-xs text-red-200/90 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2 hover:bg-red-500/15 transition-colors"
            onClick={(event) => {
              event.stopPropagation()
              onManageDependencies()
            }}
            aria-label={`View dependencies for ${thread.title}`}
          >
            <span className="font-bold">🔒 {blockingReasons[0]}</span>
            {blockingReasons.length > 1 && (
              <span className="text-red-300/80 ml-1">+{blockingReasons.length - 1} more</span>
            )}
          </button>
        )}
      </div>
      <div className="gap-2 pt-2 hidden md:flex">
        <Tooltip content="Move this thread to the front of the queue.">
          <button
            onClick={(event) => {
              event.stopPropagation()
              onMoveFront()
            }}
            className="flex-1 py-2 bg-white/5 border border-white/10 text-stone-400 rounded-xl text-[10px] font-black uppercase tracking-widest hover:bg-white/10 transition-all"
          >
            Front
          </button>
        </Tooltip>
        <Tooltip content="Choose a specific position in the queue.">
          <button
            onClick={(event) => {
              event.stopPropagation()
              onReposition()
            }}
            className="flex-1 py-2 bg-white/5 border border-white/10 text-stone-400 rounded-xl text-[10px] font-black uppercase tracking-widest hover:bg-white/10 transition-all"
          >
            Reposition
          </button>
        </Tooltip>
        <Tooltip content="Move this thread to the back of the queue.">
          <button
            onClick={(event) => {
              event.stopPropagation()
              onMoveBack()
            }}
            className="flex-1 py-2 bg-white/5 border border-white/10 text-stone-400 rounded-xl text-[10px] font-black uppercase tracking-widest hover:bg-white/10 transition-all"
          >
            Back
          </button>
        </Tooltip>
      </div>
    </div>
  )
}

export default QueueThreadCard
