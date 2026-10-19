import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Modal from './Modal'
import QueueMapSeriesDialog from './QueueMapSeriesDialog'

interface QueueBulkMapSeriesDialogProps {
  isOpen: boolean
  threadIds: number[]
  threadTitles: string[]
  onClose: () => void
  /**
   * Called once when the batch finishes, with every issue id confirmed across
   * the run. Optional: the shared series-mapping commit hook already refreshes
   * the Queue caches, so callers that only display the dialog can omit it.
   */
  onMapped?: (confirmedIssueIds: number[]) => void
  /**
   * Reports whether an unfinished batch is preserved and can be resumed.
   *
   * The Queue derives the bulk action's disabled state from the series it
   * currently shows. A search can filter out every unmapped series while a run
   * is still saved here, so the host uses this to keep `Map Series` reachable
   * and let the reader resume instead of stranding the batch. Optional: hosts
   * that do not gate the action can omit it.
   */
  onBatchPendingChange?: (hasPendingBatch: boolean) => void
}

interface BulkBatchItem {
  threadId: number
  threadTitle: string
}

type SeriesOutcome = 'pending' | 'mapped' | 'skipped'

type RunPhase = 'idle' | 'mapping' | 'results'

function buildBatch(threadIds: number[], threadTitles: string[]): BulkBatchItem[] {
  return threadIds.map((threadId, index) => ({
    threadId,
    threadTitle: threadTitles[index] ?? '',
  }))
}

function initialOutcomes(batch: BulkBatchItem[]): Record<number, SeriesOutcome> {
  const outcomes: Record<number, SeriesOutcome> = {}
  for (const item of batch) {
    outcomes[item.threadId] = 'pending'
  }
  return outcomes
}

/**
 * Bulk ComicVine mapping entry point for the Queue menu (issue #3484).
 *
 * The Queue offers a `Map Series` action that steps through every unmapped
 * series in one pass. Each series reuses the shipped {@link QueueMapSeriesDialog}
 * search/preview/approve flow, so no mapping logic is duplicated. The batch is
 * captured once when the dialog opens: a Queue refresh after a successful commit
 * (which re-creates the `threadIds`/`threadTitles` arrays) must not reset
 * progress or selections.
 *
 * A series with no safe matches, an unloadable origin, or an unavailable mapping
 * scope exposes a `Skip / needs review` action on the shared dialog so the reader
 * can reach later series instead of being trapped. Closing mid-run preserves the
 * batch; reopening the action resumes at the first unprocessed series. When every
 * series is terminal the dialog reports per-series results.
 */
export default function QueueBulkMapSeriesDialog({
  isOpen,
  threadIds,
  threadTitles,
  onClose,
  onMapped,
  onBatchPendingChange,
}: QueueBulkMapSeriesDialogProps) {
  const [phase, setPhase] = useState<RunPhase>('idle')
  const [batch, setBatch] = useState<BulkBatchItem[]>([])
  const [currentIndex, setCurrentIndex] = useState(0)
  const [outcomes, setOutcomes] = useState<Record<number, SeriesOutcome>>({})
  const [confirmedIssueIds, setConfirmedIssueIds] = useState<number[]>([])

  // The Queue re-creates these arrays on every render, so hold only the newest
  // values in a ref. Run initialization reads them when the dialog opens without
  // depending on their identity, which would reset an in-flight batch.
  const latestPropsRef = useRef({ threadIds, threadTitles })
  useEffect(() => {
    latestPropsRef.current = { threadIds, threadTitles }
  }, [threadIds, threadTitles])

  const wasOpenRef = useRef(false)
  useEffect(() => {
    const justOpened = isOpen && !wasOpenRef.current
    wasOpenRef.current = isOpen
    if (!justOpened) return

    if (phase === 'mapping') {
      // Resume the interrupted run at its first unprocessed series.
      const pendingIndex = batch.findIndex((item) => outcomes[item.threadId] === 'pending')
      if (pendingIndex >= 0) setCurrentIndex(pendingIndex)
      else setPhase('results')
      return
    }

    // Start a fresh run over the series the Queue currently reports as unmapped.
    const nextBatch = buildBatch(
      latestPropsRef.current.threadIds,
      latestPropsRef.current.threadTitles,
    )
    setBatch(nextBatch)
    setOutcomes(initialOutcomes(nextBatch))
    setConfirmedIssueIds([])
    setCurrentIndex(0)
    setPhase(nextBatch.length > 0 ? 'mapping' : 'results')
  }, [isOpen, phase, batch, outcomes])

  const currentItem = batch[currentIndex]

  // A run that is still mid-mapping is a saved batch the reader can resume.
  // Report it so the Queue keeps the bulk action enabled even when its current
  // search would otherwise hide every unmapped series.
  const hasPendingBatch = phase === 'mapping'
  useEffect(() => {
    onBatchPendingChange?.(hasPendingBatch)
  }, [hasPendingBatch, onBatchPendingChange])

  const finishCurrent = useCallback(
    (outcome: SeriesOutcome, confirmed: number[] = []) => {
      const item = batch[currentIndex]
      if (!item) return

      setOutcomes((previous) => ({ ...previous, [item.threadId]: outcome }))

      let nextConfirmed = confirmedIssueIds
      if (outcome === 'mapped' && confirmed.length > 0) {
        nextConfirmed = [...confirmedIssueIds, ...confirmed]
        setConfirmedIssueIds(nextConfirmed)
      }

      const nextIndex = currentIndex + 1
      if (nextIndex < batch.length) {
        setCurrentIndex(nextIndex)
      } else {
        setPhase('results')
        onMapped?.(nextConfirmed)
      }
    },
    [batch, confirmedIssueIds, currentIndex, onMapped],
  )

  const handleCurrentMapped = useCallback(
    (ids: number[]) => finishCurrent('mapped', ids),
    [finishCurrent],
  )

  const handleCurrentSkipped = useCallback(() => finishCurrent('skipped'), [finishCurrent])

  const handleCancel = useCallback(() => {
    // Preserve the batch so reopening the bulk action resumes where the reader stopped.
    onClose()
  }, [onClose])

  const handleDone = useCallback(() => {
    setPhase('idle')
    setBatch([])
    setOutcomes({})
    setConfirmedIssueIds([])
    setCurrentIndex(0)
    onClose()
  }, [onClose])

  const summary = useMemo(() => {
    let mapped = 0
    let skipped = 0
    for (const item of batch) {
      const outcome = outcomes[item.threadId]
      if (outcome === 'mapped') mapped += 1
      else if (outcome === 'skipped') skipped += 1
    }
    return { mapped, skipped, total: batch.length }
  }, [batch, outcomes])

  const mappingOpen = isOpen && phase === 'mapping' && currentItem != null
  const resultsOpen = isOpen && phase === 'results'

  return (
    <>
      {currentItem && (
        <QueueMapSeriesDialog
          isOpen={mappingOpen}
          threadId={currentItem.threadId}
          threadTitle={currentItem.threadTitle}
          onClose={handleCancel}
          onMapped={handleCurrentMapped}
          onSkip={handleCurrentSkipped}
        />
      )}

      <Modal isOpen={resultsOpen} title="Mapping Results" onClose={handleDone} size="large">
        <div className="space-y-4" data-testid="queue-bulk-map-series-results">
          <p className="text-sm text-[var(--theme-text-muted)]">
            Reviewed {summary.total} series.
          </p>

          {summary.mapped > 0 && (
            <div className="rounded-lg border border-[var(--theme-primary-action)]/40 bg-[var(--theme-bg-panel)] p-3">
              <p className="text-sm text-white">
                <span className="font-bold text-[var(--theme-primary-action)]">
                  {summary.mapped}
                </span>{' '}
                series mapped with{' '}
                <span className="font-bold">{confirmedIssueIds.length}</span>{' '}
                {confirmedIssueIds.length === 1 ? 'issue' : 'issues'} confirmed.
              </p>
            </div>
          )}

          {summary.skipped > 0 && (
            <div className="rounded-lg border border-[var(--theme-warning)]/40 bg-[var(--theme-bg-panel)] p-3">
              <p className="text-sm text-white">
                <span className="font-bold text-[var(--theme-warning)]">{summary.skipped}</span>{' '}
                series left for manual review.
              </p>
            </div>
          )}

          {summary.mapped === 0 && summary.skipped === 0 && (
            <p className="text-sm text-[var(--theme-text-muted)]">No series needed mapping.</p>
          )}

          <div className="flex flex-col gap-2 sm:flex-row">
            <button
              type="button"
              onClick={handleDone}
              data-testid="queue-bulk-map-series-done"
              className="min-h-11 flex-1 rounded-xl px-4 text-sm font-bold text-[var(--theme-text-primary)] bg-[var(--theme-primary-action)] hover:bg-[var(--theme-primary-action-hover)] transition"
            >
              Done
            </button>
          </div>
        </div>
      </Modal>
    </>
  )
}
