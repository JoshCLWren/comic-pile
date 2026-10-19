import { useCallback, useEffect, useMemo, useState } from 'react'
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

/**
 * The Queue rows a bulk run can map, plus the pagination state needed to read
 * the rows the reader has not scrolled to yet.
 *
 * Mirrors {@link useQueueThreads}'s result so the Queue route can hand its
 * loader straight to this hook without reshaping it.
 */
export interface QueueBulkMappingScope {
  /** Rows returned for the active Queue query. */
  data: ThreadListItem[] | null | undefined
  /** Cursor for the next unread page, or null/undefined when the queue is fully read. */
  nextPageToken: string | null | undefined
  /** True while one of those pages is in flight. */
  isLoadingMore: boolean
  /** True when the Queue query (including a page append) failed. */
  isError: boolean
  /** Appends the next cursor page. */
  loadMore: () => Promise<void>
}

export interface QueueBulkMappingDialogProps {
  isOpen: boolean
  /** True while the remaining queue pages are still loading. */
  isScopeLoading: boolean
  /** Series discovered so far as needing mapping, shown while loading. */
  scopeSeriesCount: number
  /** True when queue pages remain unread because a load failed. */
  isScopeIncomplete: boolean
  threadIds: number[]
  threadTitles: string[]
  onClose: () => void
  onBatchPendingChange: (hasPending: boolean) => void
}

export interface QueueBulkMappingState {
  /** True when no series need mapping and no saved run can be resumed. */
  bulkMapDisabled: boolean
  /** Opens the bulk dialog, resuming any batch it still holds. */
  openBulkMap: () => void
  /** Spread onto the shared bulk mapping dialog. */
  dialogProps: QueueBulkMappingDialogProps
}

/**
 * Owns the Queue's bulk `Map Series` run.
 *
 * The dialog captures its batch and preserves progress when the reader closes it
 * mid-pass. This hook tracks the visible scope and whether a saved run is still
 * pending, so the action stays enabled even after a search filters every
 * unmapped series out of view (issue #3484 review).
 *
 * An open run also finishes reading the Queue cursor before the batch is
 * captured. Without it the batch only covers the pages already on screen, so a
 * reader with 49 unmapped series across a 164-series queue silently maps a
 * subset and the results cannot explain the difference (issue #3922).
 *
 * Args:
 *   scope: The Queue rows and pagination state the run draws its batch from.
 *
 * Returns:
 *   The disabled flag, an opener, and the dialog props.
 */
export function useQueueBulkMapping(scope: QueueBulkMappingScope): QueueBulkMappingState {
  const { data, nextPageToken, isLoadingMore, isError, loadMore } = scope
  const hasMorePages = nextPageToken != null
  const [isOpen, setIsOpen] = useState(false)
  const [hasPendingBatch, setHasPendingBatch] = useState(false)

  // Declarative drain: while a run is open, keep appending cursor pages until
  // the whole queue is loaded. A failed page stops the drain so the run reports
  // a bounded batch instead of retrying forever.
  useEffect(() => {
    if (!isOpen || !hasMorePages || isLoadingMore || isError) return
    void loadMore().catch(() => undefined)
  }, [isOpen, hasMorePages, isLoadingMore, isError, loadMore])

  const isScopeLoading = isOpen && (isLoadingMore || (hasMorePages && !isError))
  const isScopeIncomplete = hasMorePages && isError

  const openBulkMap = useCallback(() => setIsOpen(true), [])
  const closeBulkMap = useCallback(() => setIsOpen(false), [])
  const onBatchPendingChange = useCallback(
    (hasPending: boolean) => setHasPendingBatch(hasPending),
    [],
  )

  const seriesNeedingMapping = useMemo(
    () =>
      (data ?? []).filter((thread) => {
        const status = thread.comicvine_mapping?.status
        return status != null && MAPPING_NEEDED_STATUSES.has(status)
      }),
    [data],
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
    () => ({
      isOpen,
      isScopeLoading,
      scopeSeriesCount: threadIds.length,
      isScopeIncomplete,
      threadIds,
      threadTitles,
      onClose: closeBulkMap,
      onBatchPendingChange,
    }),
    [
      closeBulkMap,
      isOpen,
      isScopeIncomplete,
      isScopeLoading,
      onBatchPendingChange,
      threadIds,
      threadTitles,
    ],
  )

  return {
    // Unread pages can still hold unmapped series, so the action stays reachable
    // until the whole scope has been read at least once.
    bulkMapDisabled: seriesNeedingMapping.length === 0 && !hasPendingBatch && !hasMorePages,
    openBulkMap,
    dialogProps,
  }
}