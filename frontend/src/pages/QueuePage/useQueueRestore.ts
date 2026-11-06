import { useCallback, useState } from 'react'
import { useRestoreThread } from '../../hooks/useQueue'

interface UseQueueRestoreResult {
  handleRestore: (threadId: number) => Promise<void>
  restoreError: string | null
  isRestoring: boolean
}

/**
 * Owns restoring an excluded series to the Queue, including the inline error
 * surfaced by the excluded-threads section.
 */
export function useQueueRestore(): UseQueueRestoreResult {
  const restoreMutation = useRestoreThread()
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

  return { handleRestore, restoreError, isRestoring: restoreMutation.isPending }
}
