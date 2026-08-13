import { useCallback from 'react'
import { useSnooze, useUnsnooze } from '../../hooks/useSnooze'
import { useMoveToBack, useMoveToFront, useShuffleQueue } from '../../hooks/useQueue'
import { useRollPageState, type RollPageStateSetters } from '../useRollPageState'

export function useRollSnooze(setters: RollPageStateSetters, refetchBootstrap: () => Promise<any>) {
  const snoozeMutation = useSnooze()
  const unsnoozeMutation = useUnsnooze()
  const moveToFrontMutation = useMoveToFront()
  const moveToBackMutation = useMoveToBack()
  const shuffleQueueMutation = useShuffleQueue()

  const handleUnsnooze = useCallback(async (threadId: number) => {
    try {
      await unsnoozeMutation.mutate(threadId)
      await refetchBootstrap()
    } catch (error) {
      console.error('Unsnooze failed:', error)
    }
  }, [unsnoozeMutation, refetchBootstrap])

  const handleShufflePool = useCallback(async () => {
    try {
      await shuffleQueueMutation.mutate()
      await refetchBootstrap()
    } catch (error) {
      console.error('Shuffle failed:', error)
      alert(`Failed to shuffle pool: ${error}`)
    }
  }, [shuffleQueueMutation, refetchBootstrap])

  const handleQueueAction = useCallback(async (action: 'move-front' | 'move-back' | 'snooze', threadId: number, isSnoozed: boolean) => {
    try {
      switch (action) {
        case 'move-front':
          await moveToFrontMutation.mutate(threadId)
          break
        case 'move-back':
          await moveToBackMutation.mutate(threadId)
          break
        case 'snooze':
          if (isSnoozed) {
            await unsnoozeMutation.mutate(threadId)
          } else {
            await snoozeMutation.mutate()
          }
          break
      }
      await refetchBootstrap()
    } catch (error) {
      console.error(`${action} failed:`, error)
    }
  }, [moveToFrontMutation, moveToBackMutation, snoozeMutation, unsnoozeMutation, refetchBootstrap])

  return {
    handleUnsnooze,
    handleShufflePool,
    handleQueueAction,
    snoozeMutation,
    unsnoozeMutation,
    moveToFrontMutation,
    moveToBackMutation,
    shuffleQueueMutation,
  }
}
