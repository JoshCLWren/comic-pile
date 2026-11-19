import { useCallback, useState } from 'react'
import { useRestoreExclusionGroup, useRestoreThread } from '../../hooks/useQueue'

interface UseQueueRestoreResult {
  handleRestore: (threadId: number) => Promise<void>
  handleRestoreGroup: (groupId: number) => Promise<void>
  restoreError: string | null
  isRestoring: boolean
}

/**
 * Owns restoring an excluded series or exclusion group to the Queue, including
 * the inline error surfaced by the excluded-threads section.
 */
export function useQueueRestore(): UseQueueRestoreResult {
  const restoreMutation = useRestoreThread()
  const restoreGroupMutation = useRestoreExclusionGroup()
  const [restoreError, setRestoreError] = useState<string | null>(null)

  const handleRestore = useCallback(
    async (threadId: number) => {
      setRestoreError(null)
      try {
        await restoreMutation.mutate(threadId)
      } catch {
        setRestoreError(
          'Could not restore that series to the queue. Check your connection and try again.',
        )
      }
    },
    [restoreMutation],
  )

  const handleRestoreGroup = useCallback(
    async (groupId: number) => {
      setRestoreError(null)
      try {
        await restoreGroupMutation.mutate(groupId)
      } catch {
        setRestoreError(
          'Could not restore that group to the queue. Check your connection and try again.',
        )
      }
    },
    [restoreGroupMutation],
  )

  return {
    handleRestore,
    handleRestoreGroup,
    restoreError,
    isRestoring: restoreMutation.isPending || restoreGroupMutation.isPending,
  }
}
