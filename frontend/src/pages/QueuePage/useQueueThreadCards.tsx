import { useCallback, useMemo } from 'react'
import type { BlockingDependency, SessionCurrent, ThreadListItem } from '../../types'
import { useNavigate } from 'react-router-dom'
import { canSnoozeSeries } from '../../components/snoozeAvailability'
import { useReadingBoundaries } from '../../hooks/useReadingBoundaries'
import QueueThreadCard from './QueueThreadCard'
import { useQueueCrossovers } from './useQueueCrossovers'
import type { useQueueModals } from './useQueueModals'
import type { useQueueThreadActions } from './useQueueThreadActions'

type QueueActions = ReturnType<typeof useQueueThreadActions>
type QueueModals = ReturnType<typeof useQueueModals>
const EMPTY_DEPENDENCIES: BlockingDependency[] = []

interface UseQueueThreadCardsParams {
  /** Row-action handlers from the queue actions module. */
  actions: QueueActions
  /** Active (non-completed) queue rows in server cursor order. */
  activeThreads: ThreadListItem[]
  /** Modal controllers from the queue modals module. */
  modals: QueueModals
  /** Current reading session, used to resolve per-row snooze state. */
  session?: SessionCurrent | null
  /** Whether position-based actions (move to front/back, reposition) apply. */
  positionActionsAvailable?: boolean
}

/**
 * Row rendering for the Queue list.
 *
 * This is the one place that knows how a `ThreadListItem` plus the reader's
 * blocking state, crossover groups, and session snoozes become a
 * `QueueThreadCard`. QueuePage stays a thin route composition and only
 * receives the `renderThreadCard` callback that `QueueList` calls per row; the
 * blocking and crossover reads it depends on are owned here too, so the page
 * never holds per-row derived state.
 *
 * @param params - Row actions, active rows, modal controllers, and session snooze state.
 * @returns The per-row render callback consumed by `QueueList`.
 */
export function useQueueThreadCards({
  actions,
  activeThreads,
  modals,
  session,
  positionActionsAvailable = true,
}: UseQueueThreadCardsParams) {
  const navigate = useNavigate()
  const { data: boundaryData, isPending: boundaryPending, isError: boundaryError, refetch: refetchBoundaries } = useReadingBoundaries(activeThreads.map((thread) => thread.id))
  const crossovers = useQueueCrossovers(activeThreads)
  // Memoized so the render callback keeps a stable identity across renders
  // instead of being invalidated by a fresh array on every session snapshot.
  const snoozedThreadIds = useMemo(
    () => session?.snoozed_threads?.map((t) => t.id),
    [session],
  )

  return useCallback(
    (thread: ThreadListItem, index: number) => {
      const isDragOver = actions.dragOverThreadId === thread.id
      const readingBoundary = boundaryData?.threads[thread.id]
      const isBlocked = readingBoundary && readingBoundary.state !== 'unavailable'
        ? readingBoundary.state === 'blocked'
        : thread.is_blocked
      const blockingDependencies = EMPTY_DEPENDENCIES
      const isSnoozed = snoozedThreadIds?.includes(thread.id) ?? false
      const snoozeIcon = isSnoozed ? '🔔' : '😴'
      const snoozeLabel = isSnoozed ? 'Unsnooze' : 'Snooze'
      const snoozeDisabled = !canSnoozeSeries({
        threadId: thread.id,
        isSnoozed,
        pendingThreadId: session?.pending_thread_id,
      })
      const readDisabled = isBlocked
      const blockingReasons = readingBoundary?.blockers?.map((blocker) => blocker.reason) ?? []
      const readDisabledReason =
        blockingReasons.length > 0 ? blockingReasons.join('\n') : 'Waiting for reading requirements'

      return (
        <QueueThreadCard
          key={thread.id}
          thread={thread}
          index={index}
          isBlocked={isBlocked}
          blockingDependencies={blockingDependencies}
          readingBoundary={readingBoundary}
          boundaryPending={boundaryPending}
          boundaryError={boundaryError}
          onRetryBoundaries={() => { void refetchBoundaries() }}
          crossoverGroups={crossovers.groupsForThread(thread.id)}
          crossoverGroupsLoading={crossovers.isPending}
          crossoverGroupsError={crossovers.hasError}
          isDragOver={isDragOver}
          snoozeIcon={snoozeIcon}
          snoozeLabel={snoozeLabel}
          snoozeDisabled={snoozeDisabled}
          readDisabled={readDisabled}
          readDisabledReason={readDisabledReason}
          onCardClick={() => navigate(`/thread/${thread.id}`)}
          onDragStart={actions.handleDragStart(thread.id)}
          onDragEnd={actions.handleDragEnd}
          onDragOver={actions.handleDragOver(thread.id)}
          onDrop={actions.handleDrop(thread.id, activeThreads)}
          onRead={() => void actions.handleThreadRead(thread)}
          onSnooze={() => void actions.handleSnoozeToggle(thread, isSnoozed)}
          onMoveToFront={() => actions.handleMoveToFront(thread.id)}
          onMoveToBack={() => actions.handleMoveToBack(thread.id)}
          onReposition={() => modals.openRepositionModal(thread)}
          onEdit={() => modals.showEditModal(thread)}
          onDependencies={() => modals.openDependenciesModal(thread)}
          onDelete={() => actions.requestDelete(thread)}
          onRemoveFromQueue={() => actions.requestRemove(thread)}
          positionActionsAvailable={positionActionsAvailable}
        />
      )
    },
    [actions, activeThreads, boundaryData, boundaryPending, boundaryError, refetchBoundaries, crossovers, modals, navigate, session, snoozedThreadIds, positionActionsAvailable],
  )
}
