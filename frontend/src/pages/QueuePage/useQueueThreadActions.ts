import { useCallback, useState } from 'react'
import type { DragEvent } from 'react'
import type { ThreadListItem } from '../../types'
import type { SessionRefetch } from '../../hooks/useSession'
import { threadsApi } from '../../services/api-threads'
import { focusSeriesActionsTrigger } from '../../components/seriesActionsTrigger'
import {
  useMoveToBack,
  useMoveToFront,
  useMoveToPosition,
  useShuffleQueue,
} from '../../hooks/useQueue'
import { useDeleteThread } from '../../hooks/useThread'
import { useSnooze, useUnsnooze } from '../../hooks/useSnooze'
import { useToast } from '../../contexts/useToast'
import {
  invalidateAfterQueueMutation,
  resetRollBootstrapAfterManualSelection,
} from '../../query/cacheEffects'
import { queryClient } from '../../query/queryClient'
import { getApiErrorDetail } from '../../utils/apiError'

interface UseQueueThreadActionsParams {
  navigateToRoll: (thread: ThreadListItem, response: unknown) => void
  /**
   * Refreshes the current session after a row action. The caller only needs to
   * settle, so any promise-producing refetch fits — `useSession`'s `refetch`
   * resolves with a query result rather than `void` (issue #3147).
   */
  refetchSession: SessionRefetch
  /**
   * Returns focus to a row's "Series actions" trigger once the queue cache has
   * settled. The reset that follows a queue mutation remounts every row, so
   * the trigger that opened the menu is gone by the time the mutation
   * resolves (issue #3147). Omit to use the default restore below.
   */
  restoreSeriesActionsFocus?: (threadId: number) => void
}

/**
 * Default focus restore for queue row actions. Queue mutations reset the
 * paginated queue cache, so the list unmounts and remounts while the request
 * settles; resolving the trigger by its thread id after the refetched rows
 * paint targets the same control by identity instead of by element instance,
 * so the restore survives the remount and lands on the invoking control's new
 * row position (issue #3147).
 */
function restoreSeriesActionsFocusByThreadId(threadId: number): void {
  requestAnimationFrame(() => {
    focusSeriesActionsTrigger(threadId)
  })
}

/**
 * Injectable seams for the row-action hook tree. Production callers omit
 * `deps` so every seam resolves to the real hook/service; tests substitute
 * deterministic doubles without module mocking.
 */
export interface UseQueueThreadActionsDeps {
  deleteHook?: typeof useDeleteThread
  moveToFrontHook?: typeof useMoveToFront
  moveToBackHook?: typeof useMoveToBack
  moveToPositionHook?: typeof useMoveToPosition
  shuffleHook?: typeof useShuffleQueue
  snoozeHook?: typeof useSnooze
  unsnoozeHook?: typeof useUnsnooze
  toastHook?: typeof useToast
  setPending?: typeof threadsApi.setPending
}

interface QueueThreadActionResult {
  draggedThreadId: number | null
  dragOverThreadId: number | null
  reorderError: string | null
  setReorderError: (message: string | null) => void
  handleDragStart: (threadId: number) => (event: DragEvent<HTMLElement>) => void
  handleDragOver: (threadId: number) => (event: DragEvent<HTMLElement>) => void
  handleDrop: (threadId: number, activeThreads: ThreadListItem[]) => (event: DragEvent<HTMLElement>) => void
  handleDragEnd: () => void
  pendingDeleteThread: ThreadListItem | null
  deleteError: string | null
  isDeletePending: boolean
  requestDelete: (thread: ThreadListItem) => void
  confirmDelete: () => Promise<void> | void
  cancelDelete: () => void
  isShuffleConfirmOpen: boolean
  requestShuffle: () => void
  confirmShuffle: () => Promise<void> | void
  cancelShuffle: () => void
  handleMoveToFront: (threadId: number) => Promise<void> | void
  handleMoveToBack: (threadId: number) => Promise<void> | void
  handleReposition: (threadId: number, targetPosition: number, total: number) => Promise<void> | void
  handleThreadRead: (thread: ThreadListItem) => Promise<void> | void
  handleSnoozeToggle: (thread: ThreadListItem, isSnoozed: boolean) => Promise<void> | void
}

/**
 * Owns the row-level mutation handlers and drag-and-drop reorder state for
 * the Queue list. The hook is intentionally presentation-agnostic: callers
 * pass the side-effect collaborators (navigate, refetch) and receive plain
 * event handlers back.
 */
export function useQueueThreadActions(
  params: UseQueueThreadActionsParams,
  deps: UseQueueThreadActionsDeps = {},
): QueueThreadActionResult {
  const {
    navigateToRoll,
    refetchSession,
    restoreSeriesActionsFocus = restoreSeriesActionsFocusByThreadId,
  } = params
  const {
    deleteHook = useDeleteThread,
    moveToFrontHook = useMoveToFront,
    moveToBackHook = useMoveToBack,
    moveToPositionHook = useMoveToPosition,
    shuffleHook = useShuffleQueue,
    snoozeHook = useSnooze,
    unsnoozeHook = useUnsnooze,
    toastHook = useToast,
    setPending = threadsApi.setPending,
  } = deps

  const { showToast } = toastHook()
  const deleteMutation = deleteHook()
  const moveToFrontMutation = moveToFrontHook()
  const moveToBackMutation = moveToBackHook()
  const moveToPositionMutation = moveToPositionHook()
  const shuffleQueueMutation = shuffleHook()
  const snoozeMutation = snoozeHook()
  const unsnoozeMutation = unsnoozeHook()

  const [draggedThreadId, setDraggedThreadId] = useState<number | null>(null)
  const [dragOverThreadId, setDragOverThreadId] = useState<number | null>(null)
  const [reorderError, setReorderError] = useState<string | null>(null)
  const [pendingDeleteThread, setPendingDeleteThread] = useState<ThreadListItem | null>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [isShuffleConfirmOpen, setIsShuffleConfirmOpen] = useState(false)

  const handleDragStart = useCallback(
    (threadId: number) => (event: DragEvent<HTMLElement>) => {
      event.dataTransfer.effectAllowed = 'move'
      event.dataTransfer.setData('text/plain', String(threadId))
      setDraggedThreadId(threadId)
      setReorderError(null)
    },
    [],
  )

  const handleDragOver = useCallback(
    (threadId: number) => (event: DragEvent<HTMLElement>) => {
      event.preventDefault()
      setDragOverThreadId(threadId)
    },
    [],
  )

  const handleDrop = useCallback(
    (threadId: number, activeThreads: ThreadListItem[]) =>
      (event: DragEvent<HTMLElement>) => {
        event.preventDefault()
        if (!draggedThreadId || draggedThreadId === threadId) {
          setDragOverThreadId(null)
          return
        }

        setReorderError(null)
        const targetThread = activeThreads.find((thread) => thread.id === threadId)
        if (targetThread) {
          moveToPositionMutation
            .mutate({ id: draggedThreadId, position: targetThread.queue_position })
            .then(() => {
              setReorderError(null)
            })
            .catch((error: unknown) => {
              setReorderError(getApiErrorDetail(error))
            })
        }

        setDraggedThreadId(null)
        setDragOverThreadId(null)
      },
    [draggedThreadId, moveToPositionMutation],
  )

  const handleDragEnd = useCallback(() => {
    setDraggedThreadId(null)
    setDragOverThreadId(null)
  }, [])

  const requestDelete = useCallback((thread: ThreadListItem) => {
    setDeleteError(null)
    setPendingDeleteThread(thread)
  }, [])

  const cancelDelete = useCallback(() => {
    setDeleteError(null)
    setPendingDeleteThread(null)
  }, [])

  const confirmDelete = useCallback(async () => {
    if (!pendingDeleteThread) return
    const threadId = pendingDeleteThread.id
    const threadTitle = pendingDeleteThread.title
    setDeleteError(null)
    try {
      await deleteMutation.mutate(threadId)
      setPendingDeleteThread(null)
      showToast(`Deleted "${threadTitle}"`, 'success')
    } catch (err: unknown) {
      const detail = getApiErrorDetail(err)
      setDeleteError(detail)
      showToast(`Failed to delete series: ${detail}`, 'error')
    }
  }, [pendingDeleteThread, deleteMutation, showToast])

  const handleMoveToFront = useCallback(
    (threadId: number) => {
      moveToFrontMutation.mutate(threadId)
        .then(() => {
          restoreSeriesActionsFocus(threadId)
        })
        .catch(() => {
          window.alert('Failed to move series to front. Please try again.')
        })
    },
    [moveToFrontMutation, restoreSeriesActionsFocus],
  )

  const handleMoveToBack = useCallback(
    (threadId: number) => {
      moveToBackMutation.mutate(threadId)
        .then(() => {
          restoreSeriesActionsFocus(threadId)
        })
        .catch(() => {
          window.alert('Failed to move series to back. Please try again.')
        })
    },
    [moveToBackMutation, restoreSeriesActionsFocus],
  )

  const handleReposition = useCallback(
    (threadId: number, targetPosition: number, total: number) => {
      if (targetPosition < 1 || targetPosition > total) {
        window.alert('Invalid position specified. Please choose a valid position.')
        return
      }
      moveToPositionMutation
        .mutate({ id: threadId, position: targetPosition })
        .catch(() => {
          window.alert('Failed to reposition thread. Please try again.')
        })
    },
    [moveToPositionMutation],
  )

  const requestShuffle = useCallback(() => {
    setIsShuffleConfirmOpen(true)
  }, [])

  const cancelShuffle = useCallback(() => {
    setIsShuffleConfirmOpen(false)
  }, [])

  const confirmShuffle = useCallback(async () => {
    try {
      await shuffleQueueMutation.mutate()
      setIsShuffleConfirmOpen(false)
    } catch {
      // Keep the confirmation open so the reader can retry without
      // re-clicking SHUFFLE; the dialog mirrors the delete confirmation.
      window.alert('Failed to shuffle queue. Please try again.')
    }
  }, [shuffleQueueMutation])

  const handleThreadRead = useCallback(
    async (thread: ThreadListItem) => {
      if (thread.is_blocked) {
        return
      }
      try {
        const response = await setPending(thread.id)
        // Roll hydrates the rating view from the bootstrap query, so the
        // cached snapshot must not outlive the selection we just persisted.
        await resetRollBootstrapAfterManualSelection(queryClient)
        navigateToRoll(thread, response)
      } catch (error: unknown) {
        console.error('Action failed:', error)
        window.alert(`Action failed: ${getApiErrorDetail(error)}`)
      }
    },
    [navigateToRoll, setPending],
  )

  const handleSnoozeToggle = useCallback(
    async (thread: ThreadListItem, isSnoozed: boolean) => {
      try {
        if (isSnoozed) {
          await unsnoozeMutation.mutate(thread.id)
        } else {
          // `expectedPendingThreadId` is what lets the snooze hook recover an
          // auth-failure snooze and reconcile an ambiguous network failure.
          // Dropping it would silently disable both recovery paths, so the row
          // that owns the pending thread must pass its own id (#3260).
          await snoozeMutation.mutate(thread.id)
        }
        await refetchSession()
        await invalidateAfterQueueMutation(queryClient)
        // Snooze resets the paginated queue cache, so the row remounts; the
        // id-based restore lands on the refetched trigger (#3147).
        restoreSeriesActionsFocus(thread.id)
      } catch (error: unknown) {
        console.error('Snooze action failed:', error)
        window.alert(
          `Failed to ${isSnoozed ? 'unsnooze' : 'snooze'} thread: ${getApiErrorDetail(error)}`,
        )
      }
    },
    [snoozeMutation, unsnoozeMutation, refetchSession, restoreSeriesActionsFocus],
  )

  return {
    draggedThreadId,
    dragOverThreadId,
    reorderError,
    setReorderError,
    handleDragStart,
    handleDragOver,
    handleDrop,
    handleDragEnd,
    pendingDeleteThread,
    deleteError,
    isDeletePending: deleteMutation.isPending,
    requestDelete,
    confirmDelete,
    cancelDelete,
    isShuffleConfirmOpen,
    requestShuffle,
    confirmShuffle,
    cancelShuffle,
    handleMoveToFront,
    handleMoveToBack,
    handleReposition,
    handleThreadRead,
    handleSnoozeToggle,
  }
}
