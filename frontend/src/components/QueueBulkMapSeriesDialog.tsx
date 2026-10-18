import { useCallback, useEffect, useMemo, useState } from 'react'
import Modal from './Modal'
import { comicVineApi } from '../services/api-comicvine'
import type { ComicVineSeriesResult } from '../services/api-comicvine'
import {
  useQueueMappingOriginIssue,
  useQueueSeriesMappingCommit,
  useQueueSeriesMappingPreview,
} from '../hooks/useQueueSeriesMapping'
import {
  bulkApprovableSeriesMappingRows,
  isOwnedSeriesMappingRow,
} from '../services/api-series-mapping'
import type {
  SeriesMappingClassification,
  SeriesMappingPreviewRow,
} from '../services/api-series-mapping'
import { getApiErrorDetail, isIndeterminateApiOutcome } from '../utils/apiError'

interface QueueBulkMapSeriesDialogProps {
  isOpen: boolean
  threadIds: number[]
  threadTitles: string[]
  onClose: () => void
  onMapped: (confirmedIssueIds: number[]) => void
}

type DialogStep = 'search' | 'preview' | 'results'

const SEARCH_PAGE_SIZE = 10

function stripParenthesizedYears(title: string): string {
  return title.replace(/\((\d{4}(-\d{4})?)\)/g, '').trim()
}

function seriesMetaText(series: ComicVineSeriesResult): string {
  const parts = [
    series.publisher,
    series.start_year ? `${series.start_year}` : null,
    series.issue_count ? `${series.issue_count} issues` : null,
  ].filter((part): part is string => part !== null)
  return parts.join(' · ')
}

const STATUS_LABEL: Record<SeriesMappingClassification, string> = {
  already_confirmed: 'Linked',
  safe_exact_match: 'Exact match',
  needs_review_ambiguous: 'Needs review',
  needs_review_conflict: 'Conflict',
  unresolved: 'No match',
  excluded_special: 'Special',
}

const STATUS_ACCENT_CLASS: Record<SeriesMappingClassification, string> = {
  already_confirmed: 'border-[var(--theme-border)] text-[var(--theme-text-muted)]',
  safe_exact_match: 'border-[var(--theme-comic-accent)]/40 text-[var(--theme-comic-accent)]',
  needs_review_ambiguous: 'border-[var(--theme-warning)]/40 text-[var(--theme-warning)]',
  needs_review_conflict: 'border-[var(--theme-danger)]/40 text-[var(--theme-danger)]',
  unresolved: 'border-[var(--theme-border)] text-[var(--theme-text-dim)]',
  excluded_special: 'border-[var(--theme-border)] text-[var(--theme-text-dim)]',
}

interface ThreadMappingState {
  threadId: number
  threadTitle: string
  originIssueId: number | null
  selectedSeries: ComicVineSeriesResult | null
  previewRows: SeriesMappingPreviewRow[]
  approvableRowIds: string[]
  committed: boolean
  confirmedIssueIds: number[]
  error: string | null
}

function issueNumberLabel(row: SeriesMappingPreviewRow): string {
  return row.issue_number ? `#${row.issue_number}` : 'Unnumbered'
}

/**
 * Bulk ComicVine mapping entry point for Queue menu (issue #3484).
 *
 * This dialog allows mapping multiple unmapped series in one operation.
 * It searches for each series, previews the mapping plan, and commits
 * only the safe exact matches. The flow can be cancelled and resumed,
 * and reports per-series results.
 */
export default function QueueBulkMapSeriesDialog({
  isOpen,
  threadIds,
  threadTitles,
  onClose,
  onMapped,
}: QueueBulkMapSeriesDialogProps) {
  const [step, setStep] = useState<DialogStep>('search')
  const [threadStates, setThreadStates] = useState<Record<number, ThreadMappingState>>({})
  const [currentThreadIndex, setCurrentThreadIndex] = useState(0)
  const [query, setQuery] = useState('')
  const [seriesResults, setSeriesResults] = useState<ComicVineSeriesResult[]>([])
  const [selectedSeries, setSelectedSeries] = useState<ComicVineSeriesResult | null>(null)
  const [hasMore, setHasMore] = useState(false)
  const [nextOffset, setNextOffset] = useState<number | null>(null)
  const [isSearching, setIsSearching] = useState(false)
  const [searchError, setSearchError] = useState<string | null>(null)
  const [hasSearched, setHasSearched] = useState(false)
  const [results, setResults] = useState<{
    totalThreads: number
    successfullyMapped: number
    needsReview: number
    failed: number
    confirmedIssueIds: number[]
  } | null>(null)
  const [cancelled, setCancelled] = useState(false)

  const currentThreadId = threadIds[currentThreadIndex]
  const currentThreadTitle = threadTitles[currentThreadIndex]
  const currentThreadState = threadStates[currentThreadId]

  const originQuery = useQueueMappingOriginIssue(isOpen ? currentThreadId : null, isOpen)
  const originIssueId = originQuery.data?.id ?? null
  const originReady = originQuery.isSuccess && originQuery.data !== null

  const preview = useQueueSeriesMappingPreview(
    originIssueId,
    'comicvine',
    selectedSeries ? String(selectedSeries.comicvine_volume_id) : null,
    isOpen && step === 'preview' && selectedSeries !== null,
  )
  const commit = useQueueSeriesMappingCommit()

  // Initialize thread states when dialog opens
  useEffect(() => {
    if (isOpen) {
      const initialStates: Record<number, ThreadMappingState> = {}
      threadIds.forEach((threadId, index) => {
        initialStates[threadId] = {
          threadId,
          threadTitle: threadTitles[index],
          originIssueId: null,
          selectedSeries: null,
          previewRows: [],
          approvableRowIds: [],
          committed: false,
          confirmedIssueIds: [],
          error: null,
        }
      })
      setThreadStates(initialStates)
      setCurrentThreadIndex(0)
      setStep('search')
      setQuery('')
      setSeriesResults([])
      setSelectedSeries(null)
      setHasMore(false)
      setNextOffset(null)
      setSearchError(null)
      setHasSearched(false)
      setResults(null)
      setCancelled(false)
    }
  }, [isOpen, threadIds, threadTitles])

  const handleSearch = useCallback(async (searchQuery: string, offset = 0, append = false) => {
    const trimmed = searchQuery.trim()
    if (!trimmed) {
      setSeriesResults([])
      setHasMore(false)
      setNextOffset(null)
      setHasSearched(false)
      return
    }
    setIsSearching(true)
    setSearchError(null)
    try {
      const response = await comicVineApi.searchSeries(trimmed, SEARCH_PAGE_SIZE, offset)
      setSeriesResults((previous) => {
        if (!append) return response.results
        const seen = new Set(previous.map((series) => series.comicvine_volume_id))
        return [...previous, ...response.results.filter((series) => !seen.has(series.comicvine_volume_id))]
      })
      setHasMore(response.has_more)
      setNextOffset(response.next_offset)
      setHasSearched(true)
    } catch {
      setSearchError('Failed to search ComicVine. Please try again.')
      if (!append) setSeriesResults([])
    } finally {
      setIsSearching(false)
    }
  }, [])

  useEffect(() => {
    if (isOpen && currentThreadId && step === 'search') {
      const initial = stripParenthesizedYears(currentThreadTitle)
      setQuery(initial)
      setSeriesResults([])
      setSelectedSeries(null)
      setHasMore(false)
      setNextOffset(null)
      setSearchError(null)
      setHasSearched(false)
      if (initial) void handleSearch(initial)
    }
  }, [isOpen, currentThreadId, currentThreadTitle, step, handleSearch])

  const handleQueryChange = useCallback(
    (value: string) => {
      setQuery(value)
      if (!value.trim()) {
        setHasSearched(false)
        setSeriesResults([])
        setHasMore(false)
        setNextOffset(null)
        return
      }
      const timeout = setTimeout(() => {
        void handleSearch(value)
      }, 350)
      return () => clearTimeout(timeout)
    },
    [handleSearch],
  )

  const handleLoadMore = useCallback(() => {
    if (!hasMore || nextOffset == null || isSearching) return
    void handleSearch(query, nextOffset, true)
  }, [handleSearch, hasMore, nextOffset, query, isSearching])

  const handleSelectSeries = useCallback((series: ComicVineSeriesResult) => {
    setSelectedSeries(series)
    setStep('preview')
  }, [])

  const handleBackToSearch = useCallback(() => {
    setStep('search')
    setSelectedSeries(null)
  }, [])

  const handleApproveSelected = useCallback(() => {
    if (!preview.data || !currentThreadId || !originIssueId) return

    const approvableRows = bulkApprovableSeriesMappingRows(preview.data.rows)
    const selectedRowIds = approvableRows
      .filter((row) => row.default_selected)
      .map((row) => row.row_id)

    if (selectedRowIds.length === 0) return

    const previewToken = preview.data.preview_token
    const idempotencyKey = `queue-bulk-mapping-${currentThreadId}-${originIssueId}-${preview.data.issued_at}`

    commit.mutate(
      {
        preview_token: previewToken,
        idempotency_key: idempotencyKey,
        approved_row_ids: selectedRowIds,
      },
      {
        onSuccess: (result) => {
          // Update the thread state with successful mapping
          setThreadStates((prev) => ({
            ...prev,
            [currentThreadId]: {
              ...prev[currentThreadId],
              committed: true,
              confirmedIssueIds: result.confirmed_issue_ids,
            },
          }))

          // Move to next thread or show results
          const nextIndex = currentThreadIndex + 1
          if (nextIndex < threadIds.length) {
            setCurrentThreadIndex(nextIndex)
            setStep('search')
          } else {
            // All threads processed, show results
            const allResults = Object.values(threadStates).reduce(
              (acc, state) => {
                if (state.committed) {
                  acc.successfullyMapped++
                  acc.confirmedIssueIds.push(...state.confirmedIssueIds)
                } else if (state.error) {
                  acc.failed++
                } else {
                  acc.needsReview++
                }
                return acc
              },
              {
                totalThreads: threadIds.length,
                successfullyMapped: 0,
                needsReview: 0,
                failed: 0,
                confirmedIssueIds: [] as number[],
              },
            )

            // Add the current thread's result
            if (currentThreadId in threadStates) {
              const currentState = threadStates[currentThreadId]
              if (currentState.committed) {
                allResults.successfullyMapped++
                allResults.confirmedIssueIds.push(...currentState.confirmedIssueIds)
              } else if (currentState.error) {
                allResults.failed++
              } else {
                allResults.needsReview++
              }
            }

            setResults(allResults)
            setStep('results')
          }
        },
        onError: (error) => {
          const errorDetail = getApiErrorDetail(error)
          if (errorDetail && ['preview_expired', 'preview_stale'].includes(errorDetail)) {
            // Re-read the preview instead of showing an error
            void preview.refetch()
          } else {
            // Update the thread state with error
            setThreadStates((prev) => ({
              ...prev,
              [currentThreadId]: {
                ...prev[currentThreadId],
                error: 'Could not map the series. Nothing was changed.',
              },
            }))

            // Move to next thread
            const nextIndex = currentThreadIndex + 1
            if (nextIndex < threadIds.length) {
              setCurrentThreadIndex(nextIndex)
              setStep('search')
            } else {
              // All threads processed, show results
              const allResults = Object.values(threadStates).reduce(
                (acc, state) => {
                  if (state.committed) {
                    acc.successfullyMapped++
                    acc.confirmedIssueIds.push(...state.confirmedIssueIds)
                  } else if (state.error) {
                    acc.failed++
                  } else {
                    acc.needsReview++
                  }
                  return acc
                },
                {
                  totalThreads: threadIds.length,
                  successfullyMapped: 0,
                  needsReview: 0,
                  failed: 0,
                  confirmedIssueIds: [] as number[],
                },
              )

              // Add the current thread's result
              if (currentThreadId in threadStates) {
                const currentState = threadStates[currentThreadId]
                if (currentState.committed) {
                  allResults.successfullyMapped++
                  allResults.confirmedIssueIds.push(...currentState.confirmedIssueIds)
                } else if (currentState.error) {
                  allResults.failed++
                } else {
                  allResults.needsReview++
                }
              }

              setResults(allResults)
              setStep('results')
            }
          }
        },
      },
    )
  }, [preview.data, currentThreadId, originIssueId, currentThreadIndex, threadIds, threadStates, commit])

  const handleCancel = useCallback(() => {
    setCancelled(true)
    onClose()
  }, [onClose])

  const handleResume = useCallback(() => {
    setCancelled(false)
    // Find the first unprocessed thread
    const nextIndex = threadIds.findIndex((id) => {
      const state = threadStates[id]
      return !state.committed && !state.error
    })
    
    if (nextIndex >= 0) {
      setCurrentThreadIndex(nextIndex)
      setStep('search')
      setResults(null)
    } else {
      // All threads processed, show results
      const allResults = Object.values(threadStates).reduce(
        (acc, state) => {
          if (state.committed) {
            acc.successfullyMapped++
            acc.confirmedIssueIds.push(...state.confirmedIssueIds)
          } else if (state.error) {
            acc.failed++
          } else {
            acc.needsReview++
          }
          return acc
        },
        {
          totalThreads: threadIds.length,
          successfullyMapped: 0,
          needsReview: 0,
          failed: 0,
          confirmedIssueIds: [] as number[],
        },
      )
      setResults(allResults)
      setStep('results')
    }
  }, [threadIds, threadStates])

  const dialogTitle = step === 'search' ? 'Map Series' : step === 'preview' ? 'Review Series Mapping' : 'Mapping Results'

  const progress = threadIds.length > 0 ? `${currentThreadIndex + 1} of ${threadIds.length}` : '0 of 0'

  return (
    <Modal isOpen={isOpen} title={dialogTitle} onClose={onClose} size="large">
      <div data-testid="queue-bulk-map-series-dialog">
        {step === 'search' && (
          <div className="space-y-4">
            <div className="flex justify-between items-center">
              <p className="text-sm text-stone-300">
                Map <span className="font-bold text-stone-100">{currentThreadTitle}</span>. Nothing changes
                until you review and approve the mapping plan.
              </p>
              <span className="text-xs text-stone-500 font-medium">{progress}</span>
            </div>
            <input
              type="search"
              value={query}
              onChange={(event) => handleQueryChange(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && query.trim()) {
                  void handleSearch(query)
                }
              }}
              placeholder="Search ComicVine volumes"
              aria-label="Search ComicVine volumes"
              data-testid="queue-bulk-map-series-search-input"
              className="w-full min-h-11 rounded-xl px-4 text-sm text-stone-100 bg-stone-800/50 border border-stone-700/50 placeholder:text-stone-500 focus:outline-none focus:border-amber-500/50"
            />
            {searchError && (
              <p
                role="alert"
                className="rounded-lg bg-rose-900/30 border border-rose-700/40 p-3 text-sm text-rose-200"
              >
                {searchError}
              </p>
            )}
            {originQuery.isError && (
              <p
                role="alert"
                className="rounded-lg bg-rose-900/30 border border-rose-700/40 p-3 text-sm text-rose-200"
              >
                This series could not be loaded for mapping. Please try again.
              </p>
            )}
            {originQuery.isSuccess && originQuery.data === null && (
              <p className="rounded-lg bg-stone-800/40 border border-stone-700/50 p-3 text-sm text-stone-300">
                This series has no tracked issues to map.
              </p>
            )}
            {isSearching && seriesResults.length === 0 && (
              <div className="flex justify-center py-6" aria-label="Searching">
                <div className="w-5 h-5 border-2 border-amber-500/30 border-t-amber-500 rounded-full animate-spin" />
              </div>
            )}
            {hasSearched && !isSearching && seriesResults.length === 0 && !searchError && (
              <p className="text-sm text-stone-400">No volumes matched that search.</p>
            )}
            <ul className="space-y-2 max-h-72 overflow-y-auto overscroll-contain">
              {seriesResults.map((series) => {
                const meta = seriesMetaText(series)
                return (
                  <li key={series.comicvine_volume_id}>
                    <button
                      type="button"
                      onClick={() => handleSelectSeries(series)}
                      disabled={!originReady}
                      data-testid="queue-bulk-map-series-result"
                      aria-label={meta ? `${series.name} - ${meta}` : series.name}
                      className="w-full text-left rounded-xl bg-stone-800/50 border border-stone-700/50 p-3 hover:border-amber-500/50 hover:bg-stone-800 transition disabled:opacity-50"
                    >
                      <span className="block text-sm font-bold text-stone-100">{series.name}</span>
                      {meta && <span className="block text-xs text-stone-400">{meta}</span>}
                    </button>
                  </li>
                )
              })}
            </ul>
            {hasMore && (
              <button
                type="button"
                onClick={handleLoadMore}
                disabled={isSearching}
                data-testid="queue-bulk-map-series-load-more"
                className="w-full min-h-11 rounded-xl px-4 text-sm font-bold text-stone-200 bg-stone-800/60 border border-stone-700/50 hover:bg-stone-800 transition disabled:opacity-50"
              >
                {isSearching ? 'Loading...' : 'Show more volumes'}
              </button>
            )}
          </div>
        )}

        {step === 'preview' && selectedSeries && (
          <div className="space-y-4" data-testid="queue-bulk-map-series-preview">
            <div className="flex justify-between items-center">
              <p className="text-sm text-stone-300">
                Mapping plan for <span className="font-bold text-stone-100">{selectedSeries.name}</span>. Only exact
                matches are selected; review-needed rows stay untouched.
              </p>
              <span className="text-xs text-stone-500 font-medium">{progress}</span>
            </div>
            <button
              type="button"
              onClick={handleBackToSearch}
              data-testid="queue-bulk-map-series-back"
              className="text-xs font-bold uppercase tracking-wider text-stone-400 underline underline-offset-2 hover:text-stone-200 transition-colors"
            >
              Choose a different volume
            </button>

            {preview.isPending && (
              <div className="flex justify-center py-6" aria-label="Loading mapping plan">
                <div className="w-5 h-5 border-2 border-amber-500/30 border-t-amber-500 rounded-full animate-spin" />
              </div>
            )}

            {preview.isError && (
              <div className="space-y-3">
                <p
                  role="alert"
                  className="rounded-lg bg-rose-900/30 border border-rose-700/40 p-3 text-sm text-rose-200"
                >
                  The mapping plan could not be loaded. Nothing was changed.
                </p>
                <div className="flex flex-col gap-2 sm:flex-row">
                  <button
                    type="button"
                    onClick={onClose}
                    data-testid="queue-bulk-map-series-dismiss"
                    className="min-h-11 flex-1 rounded-xl px-4 text-sm font-bold text-stone-200 bg-stone-800/60 border border-stone-700/50 hover:bg-stone-800 transition"
                  >
                    Done
                  </button>
                  <button
                    type="button"
                    onClick={() => void preview.refetch()}
                    disabled={preview.isFetching}
                    data-testid="queue-bulk-map-series-retry"
                    className="min-h-11 flex-1 rounded-xl px-4 text-sm font-bold text-stone-900 bg-amber-500 hover:bg-amber-400 transition disabled:opacity-50"
                  >
                    {preview.isFetching ? 'Retrying...' : 'Try again'}
                  </button>
                </div>
              </div>
            )}

            {preview.data && preview.data.scope.status === 'unavailable' && (
              <div className="space-y-3">
                <p className="rounded-lg bg-stone-800/40 border border-stone-700/50 p-3 text-sm text-stone-300">
                  ComicPile could not establish a safe mapping scope for this series, so there is
                  no plan to approve. Nothing was changed.
                </p>
                <button
                  type="button"
                  onClick={onClose}
                  data-testid="queue-bulk-map-series-dismiss"
                  className="w-full min-h-11 rounded-xl px-4 text-sm font-bold text-stone-200 bg-stone-800/60 border border-stone-700/50 hover:bg-stone-800 transition"
                >
                  Done
                </button>
              </div>
            )}

            {preview.data && preview.data.scope.status !== 'unavailable' && (
              <div className="space-y-3">
                {commit.isSuccess && (
                  <p
                    role="status"
                    className="rounded-lg border border-[var(--theme-primary-action)]/40 bg-stone-800/40 p-3 text-sm text-stone-100"
                  >
                    {commit.data.confirmed_issue_ids.length}{' '}
                    {commit.data.confirmed_issue_ids.length === 1 ? 'issue' : 'issues'} mapped to{' '}
                    {selectedSeries.name}.
                    {commit.data.needs_review_issue_ids.length > 0 &&
                      ` ${commit.data.needs_review_issue_ids.length} still need${
                        commit.data.needs_review_issue_ids.length === 1 ? 's' : ''
                      } review.`}
                  </p>
                )}

                {commit.isError && (
                  <p
                    role="alert"
                    className="rounded-lg bg-rose-900/30 border border-rose-700/40 p-3 text-sm text-rose-200"
                  >
                    Could not map the series. Nothing was changed.
                  </p>
                )}

                {bulkApprovableSeriesMappingRows(preview.data.rows).length === 0 && !commit.isSuccess && (
                  <p className="rounded-lg bg-stone-800/40 border border-stone-700/50 p-3 text-sm text-stone-300">
                    No exact matches for your issues in this volume. Ambiguous and special rows
                    are never mapped automatically.
                  </p>
                )}

                <ul className="space-y-2 max-h-72 overflow-y-auto overscroll-contain">
                  {preview.data.rows
                    .filter(isOwnedSeriesMappingRow)
                    .map((row) => {
                      const isApprovable = bulkApprovableSeriesMappingRows(preview.data!.rows).some(
                        (candidate) => candidate.row_id === row.row_id,
                      )
                      return (
                        <li
                          key={row.row_id}
                          data-testid="queue-bulk-map-series-row"
                          data-classification={row.classification}
                          className="flex items-center gap-3 rounded-xl bg-stone-800/50 border border-stone-700/50 p-3"
                        >
                          <span
                            className={`shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-black uppercase tracking-wider ${STATUS_ACCENT_CLASS[row.classification]}`}
                          >
                            {STATUS_LABEL[row.classification]}
                          </span>
                          <label className="min-w-0 flex-1 text-sm text-stone-100">
                            <span className="font-bold">{issueNumberLabel(row)}</span>
                            {row.title ? <span className="text-stone-300"> {row.title}</span> : null}
                          </label>
                        </li>
                      )
                    })}
                </ul>

                <div className="flex flex-col gap-2 sm:flex-row">
                  <button
                    type="button"
                    onClick={onClose}
                    disabled={commit.isPending}
                    data-testid="queue-bulk-map-series-dismiss"
                    className="min-h-11 flex-1 rounded-xl px-4 text-sm font-bold text-stone-200 bg-stone-800/60 border border-stone-700/50 hover:bg-stone-800 transition disabled:opacity-50"
                  >
                    {commit.isSuccess ? 'Done' : 'Cancel'}
                  </button>
                  {!commit.isSuccess && (
                    <button
                      type="button"
                      onClick={handleApproveSelected}
                      disabled={commit.isPending || bulkApprovableSeriesMappingRows(preview.data.rows).length === 0}
                      data-testid="queue-bulk-map-series-approve"
                      className="min-h-11 flex-1 rounded-xl px-4 text-sm font-bold text-stone-900 bg-amber-500 hover:bg-amber-400 transition disabled:opacity-50"
                    >
                      {commit.isPending
                        ? 'Mapping...'
                        : `Map ${bulkApprovableSeriesMappingRows(preview.data.rows).length} ${bulkApprovableSeriesMappingRows(preview.data.rows).length === 1 ? 'issue' : 'issues'}`}
                    </button>
                  )}
                </div>
              </div>
            )}
          </div>
        )}

        {step === 'results' && results && (
          <div className="space-y-4" data-testid="queue-bulk-map-series-results">
            <div className="flex justify-between items-center">
              <p className="text-sm text-stone-300">
                Mapping complete for {results.totalThreads} series.
              </p>
              {cancelled && (
                <span className="text-xs text-amber-400 font-medium">Cancelled</span>
              )}
            </div>

            <div className="space-y-3">
              {results.successfullyMapped > 0 && (
                <div className="rounded-lg border border-[var(--theme-primary-action)]/40 bg-stone-800/40 p-3">
                  <p className="text-sm text-stone-100">
                    <span className="font-bold text-[var(--theme-primary-action)]">{results.successfullyMapped}</span>{' '}
                    series successfully mapped with{' '}
                    <span className="font-bold">{results.confirmedIssueIds.length}</span> issues.
                  </p>
                </div>
              )}

              {results.needsReview > 0 && (
                <div className="rounded-lg border border-[var(--theme-warning)]/40 bg-stone-800/40 p-3">
                  <p className="text-sm text-stone-100">
                    <span className="font-bold text-[var(--theme-warning)]">{results.needsReview}</span>{' '}
                    series need manual review.
                  </p>
                </div>
              )}

              {results.failed > 0 && (
                <div className="rounded-lg border border-[var(--theme-danger)]/40 bg-stone-800/40 p-3">
                  <p className="text-sm text-stone-100">
                    <span className="font-bold text-[var(--theme-danger)]">{results.failed}</span>{' '}
                    series failed to map.
                  </p>
                </div>
              )}

              {cancelled && (
                <div className="rounded-lg border border-amber-500/40 bg-stone-800/40 p-3">
                  <p className="text-sm text-stone-100">
                    You can resume the mapping process where you left off.
                  </p>
                </div>
              )}
            </div>

            <div className="flex flex-col gap-2 sm:flex-row">
              <button
                type="button"
                onClick={onClose}
                className="min-h-11 flex-1 rounded-xl px-4 text-sm font-bold text-stone-200 bg-stone-800/60 border border-stone-700/50 hover:bg-stone-800 transition"
              >
                Done
              </button>
              {cancelled && (
                <button
                  type="button"
                  onClick={handleResume}
                  className="min-h-11 flex-1 rounded-xl px-4 text-sm font-bold text-stone-900 bg-amber-500 hover:bg-amber-400 transition"
                >
                  Resume Mapping
                </button>
              )}
            </div>
          </div>
        )}
      </div>
    </Modal>
  )
}