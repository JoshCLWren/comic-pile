import { useCallback, useState } from 'react'
import type { DragEvent } from 'react'
import type { Thread } from '../../types'
import { threadsApi } from '../../services/api'
import {
  useMoveToBack,
  useMoveToFront,
  useMoveToPosition,
  useShuffleQueue,
} from '../../hooks/useQueue'
import { useDeleteThread } from '../../hooks/useThread'
import { useSnooze, useUnsnooze } from '../../hooks/useSnooze'
import { invalidateAfterQueueMutation } from '../../query/cacheEffects'
import { queryClient } from '../../query/queryClient'
import { getApiErrorDetail } from '../../utils/apiError'

interface UseQueueThreadActionsParams {
  navigateToRoll: (thread: Thread, response: unknown) => void
  refetchSession: () => Promise<unknown> | unknown
}

interface QueueThreadActionResult {
  draggedThreadId: number | null
  dragOverThreadId: number | null
  reorderError: string | null
  setReorderError: (message: string | null) => void
  handleDragStart: (threadId: number) => (event: DragEvent<HTMLElement>) => void
  handleDragOver: (threadId: number) => (event: DragEvent<HTMLElement>) => void
  handleDrop: (threadId: number, activeThreads: Thread[]) => (event: DragEvent<HTMLElement>) => void
  handleDragEnd: () => void
  handleDelete: (threadId: number) => Promise<void> | void
  handleMoveToFront: (threadId: number) => Promise<void> | void
  handleMoveToBack: (threadId: number) => Promise<void> | void
  handleReposition: (threadId: number, targetPosition: number, total: number) => Promise<void> | void
  handleShuffle: () => Promise<void> | void
  handleThreadRead: (thread: Thread) => Promise<void> | void
  handleSnoozeToggle: (thread: Thread, isSnoozed: boolean) => Promise<void> | void
}

/**
 * Owns the row-level mutation handlers and drag-and-drop reorder state for
 * the Queue list. The hook is intentionally presentation-agnostic: callers
 * pass the side-effect collaborators (navigate, refetch) and receive plain
 * event handlers back.
 */
export function useQueueThreadActions(
  params: UseQueueThreadActionsParams,
): QueueThreadActionResult {
  const { navigateToRoll, refetchSession } = params
  const deleteMutation = useDeleteThread()
  const moveToFrontMutation = useMoveToFront()
  const moveToBackMutation = useMoveToBack()
  const moveToPositionMutation = useMoveToPosition()
  const shuffleQueueMutation = useShuffleQueue()
  const snoozeMutation = useSnooze()
  const unsnoozeMutation = useUnsnooze()

  const [draggedThreadId, setDraggedThreadId] = useState<number | null>(null)
  const [dragOverThreadId, setDragOverThreadId] = useState<number | null>(null)
  const [reorderError, setReorderError] = useState<string | null>(null)

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
    (threadId: number, activeThreads: Thread[]) =>
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

  const handleDelete = useCallback(
    (threadId: number) => {
      if (!window.confirm('Are you sure you want to delete this thread?')) {
        return
      }
      deleteMutation.mutate(threadId)
        .catch((err: unknown) => {
          window.alert(`Failed to delete thread: ${getApiErrorDetail(err)}`)
        })
    },
    [deleteMutation],
  )

  const handleMoveToFront = useCallback(
    (threadId: number) => {
      moveToFrontMutation.mutate(threadId)
        .catch(() => {
          window.alert('Failed to move thread to front. Please try again.')
        })
    },
    [moveToFrontMutation],
  )

  const handleMoveToBack = useCallback(
    (threadId: number) => {
      moveToBackMutation.mutate(threadId)
        .catch(() => {
          window.alert('Failed to move thread to back. Please try again.')
        })
    },
    [moveToBackMutation],
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

  const handleShuffle = useCallback(async () => {
    try {
      await shuffleQueueMutation.mutate()
    } catch {
      window.alert('Failed to shuffle queue. Please try again.')
    }
  }, [shuffleQueueMutation])

  const handleThreadRead = useCallback(
    async (thread: Thread) => {
      if (thread.is_blocked) {
        window.alert('Cannot read yet:\n\nThis thread is blocked by a dependency.')
        return
      }
      try {
        const response = await threadsApi.setPending(thread.id)
        navigateToRoll(thread, response)
      } catch (error: unknown) {
        console.error('Action failed:', error)
        window.alert(`Action failed: ${getApiErrorDetail(error)}`)
      }
    },
    [navigateToRoll],
  )

  const handleSnoozeToggle = useCallback(
    async (thread: Thread, isSnoozed: boolean) => {
      try {
        if (isSnoozed) {
          await unsnoozeMutation.mutate(thread.id)
        } else {
          await snoozeMutation.mutate(thread.id)
        }
        await refetchSession()
        await invalidateAfterQueueMutation(queryClient)
      } catch (error: unknown) {
        console.error('Snooze action failed:', error)
        window.alert(
          `Failed to ${isSnoozed ? 'unsnooze' : 'snooze'} thread: ${getApiErrorDetail(error)}`,
        )
      }
    },
    [snoozeMutation, unsnoozeMutation, refetchSession],
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
    handleDelete,
    handleMoveToFront,
    handleMoveToBack,
    handleReposition,
    handleShuffle,
    handleThreadRead,
    handleSnoozeToggle,
  }
}
