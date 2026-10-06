import { useCallback, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import type { ThreadListItem } from '../../types'

/**
 * Queue-level ComicVine mapping affordances for issue #3201.
 *
 * The Queue page stays a thin route composition (see
 * `QueuePage.composition.test.ts`), so the bulk-mapping dialog state and the
 * per-card "map this series" navigation live here instead of in the page.
 */
export function isQueueThreadMapped(thread: ThreadListItem): boolean {
  // The queue list payload does not expose mapping status yet, so a known
  // issue total is the current mapped signal. Series that entered the queue
  // through ComicVine resolution carry totals; unmapped local series do not.
  return thread.total_issues !== null
}

export interface UseQueueComicVineMappingResult {
  bulkMapDialogOpen: boolean
  selectedThreadsForMapping: ThreadListItem[]
  handleBulkMapComicVine: () => void
  handleMapSelectedThreads: () => void
  handleMapSingleThread: (thread: ThreadListItem) => void
  closeBulkMapDialog: () => void
}

/**
 * Own the "Map all unmapped series" flow and the per-card mapping entry
 * point. Both navigate to the Roll page with a manual-roll payload so the
 * existing Roll mapping flow handles the selected series.
 *
 * @param activeThreads - Active queue threads used to derive the unmapped set.
 */
export function useQueueComicVineMapping(
  activeThreads: ThreadListItem[],
): UseQueueComicVineMappingResult {
  const navigate = useNavigate()
  const [bulkMapDialogOpen, setBulkMapDialogOpen] = useState(false)
  const [selectedThreadsForMapping, setSelectedThreadsForMapping] = useState<ThreadListItem[]>([])

  const handleBulkMapComicVine = useCallback(() => {
    const unmappedThreads = activeThreads.filter((thread) => !isQueueThreadMapped(thread))

    if (unmappedThreads.length === 0) {
      window.alert('All series are already mapped to ComicVine!')
      return
    }

    setSelectedThreadsForMapping(unmappedThreads)
    setBulkMapDialogOpen(true)
  }, [activeThreads])

  const handleMapSelectedThreads = useCallback(() => {
    selectedThreadsForMapping.forEach((thread) => {
      navigate('/', { state: { rollResponse: { thread_id: thread.id, result: 'manual' } } })
    })
    setBulkMapDialogOpen(false)
    setSelectedThreadsForMapping([])
  }, [selectedThreadsForMapping, navigate])

  const handleMapSingleThread = useCallback(
    (thread: ThreadListItem) => {
      navigate('/', { state: { rollResponse: { thread_id: thread.id, result: 'manual' } } })
    },
    [navigate],
  )

  const closeBulkMapDialog = useCallback(() => {
    setBulkMapDialogOpen(false)
  }, [])

  return {
    bulkMapDialogOpen,
    selectedThreadsForMapping,
    handleBulkMapComicVine,
    handleMapSelectedThreads,
    handleMapSingleThread,
    closeBulkMapDialog,
  }
}
