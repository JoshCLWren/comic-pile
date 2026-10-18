import { useCallback, useMemo, useState } from 'react'
import type { ThreadListItem } from '../../types'

/**
 * Mapping health values that still offer the per-row `Map series` repair action.
 * Fully mapped and non-issue-tracked series are intentionally excluded, so the
 * bulk action's scope matches what the Queue surfaces for repair.
 */
const MAPPING_NEEDED_STATUSES: ReadonlySet<string> = new Set([
  'unresolved',
  'partial',
  'needs_review',
])

export interface QueueBulkMappingDialogProps {
  isOpen: boolean
  threadIds: number[]
  threadTitles: string[]
  onClose: () => void
  onBatchPendingChange: (hasPending: boolean) => void
}

export interface QueueBulkMappingState {
  /** True when no visible series need mapping and no saved run can be resumed. */
  bulkMapDisabled: boolean
  /** Opens the bulk dialog, resuming any batch it still holds. */
  openBulkMap: () => void
  /** Spread onto the shared bulk mapping dialog. */
  dialogProps: QueueBulkMappingDialogProps
}

/**
 * Owns the Queue's bulk `Map Series` run.
 *
 * The dialog captures its batch when it opens and preserves progress when the
 * reader closes it mid-pass. This hook tracks the visible scope and whether a
 * saved run is still pending, so the action stays enabled even after a search
 * filters every unmapped series out of view (issue #3484 review).
 *
 * Args:
 *   threads: The Queue rows currently returned for the active search.
 *
 * Returns:
 *   The disabled flag, an opener, and the dialog props.
 */
export function useQueueBulkMapping(
  threads: ThreadListItem[] | null | undefined,
): QueueBulkMappingState {
  const [isOpen, setIsOpen] = useState(false)
  const [hasPendingBatch, setHasPendingBatch] = useState(false)

  const openBulkMap = useCallback(() => setIsOpen(true), [])
  const closeBulkMap = useCallback(() => setIsOpen(false), [])
  const onBatchPendingChange = useCallback(
    (hasPending: boolean) => setHasPendingBatch(hasPending),
    [],
  )

  const seriesNeedingMapping = useMemo(
    () =>
      (threads ?? []).filter((thread) => {
        const status = thread.comicvine_mapping?.status
        return status != null && MAPPING_NEEDED_STATUSES.has(status)
      }),
    [threads],
  )

  const threadIds = useMemo(
    () => seriesNeedingMapping.map((thread) => thread.id),
    [seriesNeedingMapping],
  )
  const threadTitles = useMemo(
    () => seriesNeedingMapping.map((thread) => thread.title),
    [seriesNeedingMapping],
  )

  const dialogProps = useMemo(
    () => ({ isOpen, threadIds, threadTitles, onClose: closeBulkMap, onBatchPendingChange }),
    [isOpen, threadIds, threadTitles, closeBulkMap, onBatchPendingChange],
  )

  return {
    bulkMapDisabled: seriesNeedingMapping.length === 0 && !hasPendingBatch,
    openBulkMap,
    dialogProps,
  }
}
