import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Modal from './Modal'
import QueueMapSeriesDialog from './QueueMapSeriesDialog'
import type { SeriesBatchProgress, SeriesMappingFailure } from './QueueMapSeriesDialog'

interface QueueBulkMapSeriesDialogProps {
  isOpen: boolean
  /**
   * True while the Queue is still loading the pages that hold series needing
   * mapping. The batch is not captured until this clears, so a run covers every
   * series that needs mapping rather than only the pages the reader scrolled
   * (issue #3922).
   */
  isScopeLoading?: boolean
  /**
   * Series already discovered as needing mapping, shown while the remaining
   * queue pages load. Optional: hosts that cannot report a running count omit
   * it.
   */
  scopeSeriesCount?: number
  /**
   * True when the Queue still reports unmapped series it could not load. The
   * results explain that this run may not cover every series, instead of
   * quietly presenting a partial batch as complete.
   */
  isScopeIncomplete?: boolean
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
   * Called once per open when the run's batch is fixed: a fresh run captured
   * it, or a saved run resumed. The host stops preparing and draining from
   * here — a queue refresh after a saved mapping drops the loaded pages, and
   * re-draining would reopen the preparing dialog beneath the mapping or
   * results dialog after every saved series. Optional: hosts that do not drain
   * the Queue cursor can omit it.
   */
  onBatchCaptured?: () => void
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

type SeriesOutcome = 'pending' | 'mapped' | 'skipped' | 'failed'

type RunPhase = 'idle' | 'mapping' | 'results'

const OUTCOME_LABEL: Record<SeriesOutcome, string> = {
  pending: 'Not reviewed',
  mapped: 'Mapped',
  skipped: 'Needs review',
  failed: 'Failed',
}

/**
 * Status chips carry their meaning in the label as well as the accent, so the
 * result is readable without relying on color.
 */
const OUTCOME_ACCENT: Record<SeriesOutcome, string> = {
  pending: 'border-[var(--theme-border)] text-[var(--theme-text-dim)]',
  mapped: 'border-[var(--theme-primary-action)]/40 text-[var(--theme-primary-action)]',
  skipped: 'border-[var(--theme-warning)]/40 text-[var(--theme-warning)]',
  failed: 'border-[var(--theme-danger)]/40 text-[var(--theme-danger)]',
}

/** Plain-language reason a series failed, so the list explains itself. */
const FAILURE_DETAIL: Record<SeriesMappingFailure, string> = {
  origin_unavailable: 'the series could not be loaded',
  no_tracked_issues: 'the series has no tracked issues',
  preview_unavailable: 'the mapping plan could not be loaded',
  scope_unavailable: 'no safe mapping scope was available',
  commit_failed: 'the mapping could not be saved',
  commit_outcome_unknown: 'the save result could not be confirmed; the mapping may have applied',
}

function buildBatch(threadIds: number[], threadTitles: string[]): BulkBatchItem[] {
  return threadIds.map((threadId, index) => ({
    threadId,
    threadTitle: threadTitles[index] ?? '',
  }))
}

function initialOutcomes(batch: BulkBatchItem[]) {
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
 * captured once the whole scope has loaded: a Queue refresh after a successful
 * commit (which re-creates the `threadIds`/`threadTitles` arrays) must not reset
 * progress or selections.
 *
 * A series with no safe matches exposes a `Skip / needs review` action on the
 * shared dialog so the reader can reach later series instead of being trapped,
 * and a series that could not be mapped in this pass (an unloadable origin, no
 * tracked issues, an unavailable mapping scope, or a refused commit) reports a
 * failure instead so the two are never conflated. An unconfirmed commit outcome
 * (a lost response or server error may have saved the mapping) is reported as
 * needing review with that reason instead of as a failed save. Closing mid-run
 * preserves the batch; reopening the action resumes at the first unprocessed
 * series.
 *
 * Every step reports its position in the batch, and a `Finish & show results`
 * action ends a long run early instead of forcing the reader to process every
 * series. The results screen then reports each series by name with its own
 * mapped / skipped / failed outcome plus separate counts (issue #3922).
 */
export default function QueueBulkMapSeriesDialog({
  isOpen,
  isScopeLoading = false,
  scopeSeriesCount = 0,
  isScopeIncomplete = false,
  threadIds,
  threadTitles,
  onClose,
  onMapped,
  onBatchCaptured,
  onBatchPendingChange,
}: QueueBulkMapSeriesDialogProps) {
  const [phase, setPhase] = useState<RunPhase>('idle')
  const [batch, setBatch] = useState<BulkBatchItem[]>([])
  const [currentIndex, setCurrentIndex] = useState(0)
  const [outcomes, setOutcomes] = useState<Record<number, SeriesOutcome>>({})
  const [failures, setFailures] = useState<Record<number, SeriesMappingFailure>>({})
  const [confirmedByThread, setConfirmedByThread] = useState<Record<number, number>>({})
  const [confirmedIssueIds, setConfirmedIssueIds] = useState<number[]>([])
  const [batchIncomplete, setBatchIncomplete] = useState(false)

  // The Queue re-creates these arrays on every render, so hold only the newest
  // values in a ref. Run initialization reads them when the dialog opens without
  // depending on their identity, which would reset an in-flight batch.
  const latestPropsRef = useRef({ threadIds, threadTitles })
  useEffect(() => {
    latestPropsRef.current = { threadIds, threadTitles }
  }, [threadIds, threadTitles])

  /**
   * Returns the run to the first series that has no outcome yet. Used both when
   * a saved batch is resumed and when the reader continues after finishing a run
   * early, so the results screen is never a dead end.
   */
  const resumeAtFirstPending = useCallback(() => {
    const pendingIndex = batch.findIndex((item) => outcomes[item.threadId] === 'pending')
    if (pendingIndex < 0) {
      // Every series already has an outcome, so results is the only truthful screen.
      setPhase('results')
      return
    }
    setCurrentIndex(pendingIndex)
    setPhase('mapping')
  }, [batch, outcomes])

  const wasOpenRef = useRef(false)
  useEffect(() => {
    if (!isOpen) {
      // Reopening after a close is a fresh open transition, even when the run
      // itself is still saved here.
      wasOpenRef.current = false
      return
    }
    // Capture waits for the whole scope: a batch built from the pages loaded so
    // far silently omits every unmapped series the reader never scrolled to.
    if (isScopeLoading) return

    const justOpened = !wasOpenRef.current
    wasOpenRef.current = true
    if (!justOpened) return

    if (phase === 'mapping') {
      // Resume the interrupted run at its first unprocessed series. The saved
      // batch already fixed this run's scope, so the host stops preparing.
      resumeAtFirstPending()
      onBatchCaptured?.()
      return
    }

    // Start a fresh run over the series the Queue currently reports as unmapped.
    const nextBatch = buildBatch(
      latestPropsRef.current.threadIds,
      latestPropsRef.current.threadTitles,
    )
    setBatch(nextBatch)
    setOutcomes(initialOutcomes(nextBatch))
    setFailures({})
    setConfirmedByThread({})
    setConfirmedIssueIds([])
    setCurrentIndex(0)
    setBatchIncomplete(isScopeIncomplete)
    setPhase(nextBatch.length > 0 ? 'mapping' : 'results')
    // The batch is fixed from here on: a queue refresh after a saved mapping
    // drops the loaded pages, and re-draining would reopen the preparing dialog
    // beneath the mapping or results dialog after every saved series.
    onBatchCaptured?.()
  // eslint-disable-next-line react-hooks/exhaustive-deps
}, [isOpen, isScopeLoading, phase, resumeAtFirstPending, onBatchCaptured])

  const currentItem = batch[currentIndex]

  // A run that is still mid-mapping is a saved batch the reader can resume.
  // Report it so the Queue keeps the bulk action enabled even when its current
  // search would otherwise hide every unmapped series.
  const hasPendingBatch = isScopeLoading || phase === 'mapping'
  useEffect(() => {
    onBatchPendingChange?.(hasPendingBatch)
  }, [hasPendingBatch, onBatchPendingChange])

  const finishCurrent = useCallback(
    (outcome: SeriesOutcome, confirmed: number[] = [], failure?: SeriesMappingFailure) => {
      const item = batch[currentIndex]
      if (!item) return

      setOutcomes((previous) => ({ ...previous, [item.threadId]: outcome }))

      // The reason is recorded for any outcome that carries one, so a series
      // left for review can still explain why (an unconfirmed commit outcome).
      if (failure) {
        setFailures((previous) => ({ ...previous, [item.threadId]: failure }))
      }

      if (outcome === 'mapped' && confirmed.length > 0) {
        setConfirmedByThread((previous) => ({
          ...previous,
          [item.threadId]: confirmed.length,
        }))
      }

      let nextConfirmed = confirmedIssueIds
      if (outcome === 'mapped' && confirmed.length > 0) {
        nextConfirmed = [...confirmedIssueIds, ...confirmed]
        setConfirmedIssueIds(nextConfirmed)
      }

      const nextIndex = currentIndex + 1
      if (nextIndex < batch.length) {
        setCurrentIndex(nextIndex)
        return
      }

      setPhase('results')
      onMapped?.(nextConfirmed)
    },
    [batch, confirmedIssueIds, currentIndex, onMapped],
  )

  const handleCurrentMapped = useCallback(
    (ids: number[]) => finishCurrent('mapped', ids),
    [finishCurrent],
  )

  const handleCurrentSkipped = useCallback(() => finishCurrent('skipped'), [finishCurrent])

  const handleCurrentFailed = useCallback(
    (reason: SeriesMappingFailure) => {
      // An unconfirmed commit outcome is not a known failure: the mapping may
      // have saved (issue #3776), so the results mark the series as needing
      // review instead of counting it as failed.
      if (reason === 'commit_outcome_unknown') {
        finishCurrent('skipped', [], reason)
        return
      }
      finishCurrent('failed', [], reason)
    },
    [finishCurrent],
  )

  const handleCancel = useCallback(() => {
    // Preserve the batch so reopening the bulk action resumes where the reader stopped.
    onClose()
  }, [onClose])

  /**
   * Ends the run early. Every series still unreviewed stays in the batch, so the
   * results screen reports it and the reader can continue from there.
   */
  const handleFinish = useCallback(() => {
    setPhase('results')
    onMapped?.(confirmedIssueIds)
  }, [confirmedIssueIds, onMapped])

  const handleDone = useCallback(() => {
    setPhase('idle')
    setBatch([])
    setOutcomes({})
    setFailures({})
    setConfirmedByThread({})
    setConfirmedIssueIds([])
    setCurrentIndex(0)
    setBatchIncomplete(false)
    onClose()
  }, [onClose])

  const summary = useMemo(() => {
    let mapped = 0
    let skipped = 0
    let failed = 0
    let reviewed = 0
    for (const item of batch) {
      const outcome = outcomes[item.threadId]
      if (outcome === 'mapped') mapped += 1
      else if (outcome === 'skipped') skipped += 1
      else if (outcome === 'failed') failed += 1
      if (outcome !== undefined && outcome !== 'pending') reviewed += 1
    }
    return {
      mapped,
      skipped,
      failed,
      reviewed,
      total: batch.length,
      remaining: batch.length - reviewed,
    }
  }, [batch, outcomes])

  const batchProgress = useMemo<SeriesBatchProgress | undefined>(
    () =>
      phase === 'mapping' && currentItem
        ? {
            position: currentIndex + 1,
            total: batch.length,
            mapped: summary.mapped,
            skipped: summary.skipped,
            failed: summary.failed,
          }
        : undefined,
    [
      batch.length,
      currentIndex,
      currentItem,
      phase,
      summary.failed,
      summary.mapped,
      summary.skipped,
    ],
  )

  const preparingOpen = isOpen && isScopeLoading
  const mappingOpen = isOpen && phase === 'mapping' && currentItem != null
  const resultsOpen = isOpen && phase === 'results'

  return (
    <>
      <Modal isOpen={preparingOpen} title="Map Series" onClose={handleCancel} size="default">
        <div className="space-y-3" data-testid="queue-bulk-map-series-preparing">
          <div className="flex justify-center py-4" aria-label="Loading series">
            <div className="w-5 h-5 border-2 border-[var(--theme-border)] border-t-[var(--theme-primary-action)] rounded-full animate-spin" />
          </div>
          <p className="text-sm text-[var(--theme-text-muted)]">
            Loading the whole queue so the batch covers every series that still needs a ComicVine
            match, not only the pages already on screen.
          </p>
          {scopeSeriesCount > 0 && (
            <p className="text-xs text-[var(--theme-text-dim)]">
              {scopeSeriesCount} series found so far
            </p>
          )}
        </div>
      </Modal>

      {currentItem && (
        <>
          {batchIncomplete && (
            <p
              role="alert"
              className="rounded-lg border border-[var(--theme-warning)]/40 bg-[var(--theme-bg-panel)] p-3 text-sm text-[var(--theme-text-primary)]"
            >
              Part of the queue could not be loaded, so this run may not cover every series that
              needs a ComicVine match. Reopen Map Series once the queue finishes loading to include
              the rest.
            </p>
          )}
          <QueueMapSeriesDialog
            isOpen={mappingOpen}
            threadId={currentItem.threadId}
            threadTitle={currentItem.threadTitle}
            onClose={handleCancel}
            onMapped={handleCurrentMapped}
            onSkip={handleCurrentSkipped}
            onFailed={handleCurrentFailed}
            batchProgress={batchProgress}
            onFinishBatch={handleFinish}
          />
        </>
      )}

      <Modal isOpen={resultsOpen} title="Mapping Results" onClose={handleDone} size="large">
        <div className="space-y-4" data-testid="queue-bulk-map-series-results">
          <p
            className="text-sm text-[var(--theme-text-muted)]"
            data-testid="queue-bulk-map-series-summary"
          >
            {summary.total === 0
              ? 'No series needed mapping.'
              : summary.remaining === 0
                ? `Reviewed all ${summary.total} series.`
                : `Reviewed ${summary.reviewed} of ${summary.total} series.`}
          </p>

          {batchIncomplete && (
            <p
              role="alert"
              className="rounded-lg border border-[var(--theme-warning)]/40 bg-[var(--theme-bg-panel)] p-3 text-sm text-[var(--theme-text-primary)]"
            >
              Part of the queue could not be loaded, so this run may not cover every series that
              needs a ComicVine match. Reopen Map Series once the queue finishes loading to include
              the rest.
            </p>
          )}

          {summary.total > 0 && (
            <>
              <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                {(
                  [
                    ['mapped', summary.mapped],
                    ['skipped', summary.skipped],
                    ['failed', summary.failed],
                    ['pending', summary.remaining],
                  ] as const
                ).map(([outcome, count]) => (
                  <div
                    key={outcome}
                    className="rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] p-3"
                    data-testid={`queue-bulk-map-series-count-${outcome}`}
                    data-count={count}
                  >
                    <dt className="text-[10px] font-black uppercase tracking-widest text-[var(--theme-text-dim)]">
                      {OUTCOME_LABEL[outcome]}
                    </dt>
                    <dd className="text-xl font-black tabular-nums text-[var(--theme-text-primary)]">
                      {count}
                    </dd>
                  </div>
                ))}
              </dl>

              {confirmedIssueIds.length > 0 && (
                <p
                  className="text-sm text-[var(--theme-text-muted)]"
                  data-testid="queue-bulk-map-series-confirmed"
                >
                  {confirmedIssueIds.length}{' '}
                  {confirmedIssueIds.length === 1 ? 'issue' : 'issues'} confirmed across this run.
                </p>
              )}

              {/* Per-series results (#3484/#3922): the aggregate counts above do not
                  tell a reader which of 44 series actually got mapped. */}
              <ul
                className="max-h-72 space-y-2 overflow-y-auto overscroll-contain"
                data-testid="queue-bulk-map-series-list"
              >
                {batch.map((item) => {
                  const outcome = outcomes[item.threadId] ?? 'pending'
                  const failure = failures[item.threadId]
                  const confirmed = confirmedByThread[item.threadId] ?? 0
                  return (
                    <li
                      key={item.threadId}
                      className="flex items-center justify-between gap-3 rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-3 py-2"
                      data-testid="queue-bulk-map-series-result-row"
                      data-outcome={outcome}
                    >
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm text-[var(--theme-text-primary)]">
                          {item.threadTitle}
                        </span>
                        {failure && (
                          <span className="block truncate text-xs text-[var(--theme-text-dim)]">
                            {FAILURE_DETAIL[failure]}
                          </span>
                        )}
                        {outcome === 'mapped' && confirmed > 0 && (
                          <span className="block text-xs text-[var(--theme-text-dim)]">
                            {confirmed} {confirmed === 1 ? 'issue' : 'issues'} confirmed
                          </span>
                        )}
                      </span>
                      <span
                        className={`shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-black uppercase tracking-wider ${OUTCOME_ACCENT[outcome]}`}
                      >
                        {OUTCOME_LABEL[outcome]}
                      </span>
                    </li>
                  )
                })}
              </ul>
            </>
          )}

          <div className="flex flex-col gap-2 sm:flex-row">
            {summary.remaining > 0 && (
              <button
                type="button"
                onClick={resumeAtFirstPending}
                data-testid="queue-bulk-map-series-continue"
                className="min-h-11 flex-1 rounded-xl px-4 text-sm font-bold text-[var(--theme-text-primary)] border border-[var(--theme-border)] hover:bg-[var(--theme-bg-hover)] transition"
              >
                Continue mapping
              </button>
            )}
            <button
              type="button"
              onClick={handleDone}
              data-testid="queue-bulk-map-series-done"
              className="min-h-11 flex-1 rounded-xl px-4 text-sm font-bold text-stone-950 bg-[var(--theme-primary-action)] hover:bg-[var(--theme-primary-action-hover)] transition"
            >
              Done
            </button>
          </div>
        </div>
      </Modal>
    </>
  )
}