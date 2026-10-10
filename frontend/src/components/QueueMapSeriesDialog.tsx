import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
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
import { getApiErrorDetail } from '../utils/apiError'

interface QueueMapSeriesDialogProps {
  isOpen: boolean
  threadId: number
  threadTitle: string
  onClose: () => void
  onMapped: (confirmedIssueIds: number[]) => void
}

type DialogStep = 'search' | 'preview'

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

/**
 * Commit refusals that mean the preview the reader approved is no longer current.
 *
 * The preview token is user-bound and expires, so these re-read the plan instead of
 * retrying a request the server will refuse again.
 */
const STALE_PREVIEW_DETAILS = new Set(['preview_expired', 'preview_stale'])

function issueNumberLabel(row: SeriesMappingPreviewRow): string {
  return row.issue_number ? `#${row.issue_number}` : 'Unnumbered'
}

/**
 * Thread-level ComicVine repair entry point for Queue rows (issue #2773).
 *
 * The indicator shows mapping health from the paginated Queue response; this dialog
 * is the `Map series` repair side. It searches provider volumes for the thread title,
 * requests the shared read-only series-mapping preview (#2721) anchored on the
 * thread's origin issue, and commits only the rows the preview classified as safe
 * exact matches (#2722). Ambiguous, conflicting, unresolved, and special rows stay
 * untouched and are reported. Canceling or failing never mutates Queue state; a
 * successful commit refreshes the Queue through the shared commit hook so the
 * indicator updates without a hard reload.
 *
 * Provider and issue requests start only when the reader opens this dialog. Queue
 * rendering itself makes no per-card requests.
 */
export default function QueueMapSeriesDialog({
  isOpen,
  threadId,
  threadTitle,
  onClose,
  onMapped,
}: QueueMapSeriesDialogProps) {
  const [step, setStep] = useState<DialogStep>('search')
  const [query, setQuery] = useState(threadTitle)
  const [seriesResults, setSeriesResults] = useState<ComicVineSeriesResult[]>([])
  const [selectedSeries, setSelectedSeries] = useState<ComicVineSeriesResult | null>(null)
  const [hasMore, setHasMore] = useState(false)
  const [nextOffset, setNextOffset] = useState<number | null>(null)
  const [isSearching, setIsSearching] = useState(false)
  const [searchError, setSearchError] = useState<string | null>(null)
  const [hasSearched, setHasSearched] = useState(false)
  const [uncheckedRowIds, setUncheckedRowIds] = useState<ReadonlySet<string>>(() => new Set())
  const asyncRef = useRef(0)
  const searchingRef = useRef(false)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const originQuery = useQueueMappingOriginIssue(isOpen ? threadId : null, isOpen)
  const originIssueId = originQuery.data?.id ?? null
  // The preview anchors on one owned issue. While the anchor is unknown the
  // volume list stays disabled so the reader can never reach a preview step
  // that cannot load.
  const originReady = originQuery.isSuccess && originQuery.data !== null

  const preview = useQueueSeriesMappingPreview(
    originIssueId,
    'comicvine',
    selectedSeries ? String(selectedSeries.comicvine_volume_id) : null,
    isOpen && step === 'preview' && selectedSeries !== null,
  )
  const commit = useQueueSeriesMappingCommit()

  useEffect(() => {
    return () => {
      if (debounceRef.current) {
        clearTimeout(debounceRef.current)
        debounceRef.current = null
      }
    }
  }, [])

  const handleSearch = useCallback(async (searchQuery: string, offset = 0, append = false) => {
    const trimmed = searchQuery.trim()
    if (!trimmed) {
      setSeriesResults([])
      setHasMore(false)
      setNextOffset(null)
      setHasSearched(false)
      return
    }
    const requestId = ++asyncRef.current
    searchingRef.current = true
    setIsSearching(true)
    setSearchError(null)
    try {
      const response = await comicVineApi.searchSeries(trimmed, SEARCH_PAGE_SIZE, offset)
      if (requestId !== asyncRef.current) return
      setSeriesResults((previous) => {
        if (!append) return response.results
        const seen = new Set(previous.map((series) => series.comicvine_volume_id))
        return [...previous, ...response.results.filter((series) => !seen.has(series.comicvine_volume_id))]
      })
      setHasMore(response.has_more)
      setNextOffset(response.next_offset)
      setHasSearched(true)
    } catch {
      if (requestId !== asyncRef.current) return
      setSearchError('Failed to search ComicVine. Please try again.')
      if (!append) setSeriesResults([])
    } finally {
      if (requestId === asyncRef.current) {
        setIsSearching(false)
        searchingRef.current = false
      }
    }
  }, [])

  useEffect(() => {
    if (isOpen) {
      const initial = stripParenthesizedYears(threadTitle)
      setStep('search')
      setQuery(initial)
      setSeriesResults([])
      setSelectedSeries(null)
      setHasMore(false)
      setNextOffset(null)
      setSearchError(null)
      setHasSearched(false)
      setUncheckedRowIds(new Set())
      commit.reset()
      if (initial) void handleSearch(initial)
    }
    // Reset only on open transitions; the search callback is stable.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen, threadId])

  const handleQueryChange = useCallback(
    (value: string) => {
      setQuery(value)
      if (debounceRef.current) clearTimeout(debounceRef.current)
      if (!value.trim()) {
        setHasSearched(false)
        setSeriesResults([])
        setHasMore(false)
        setNextOffset(null)
        return
      }
      debounceRef.current = setTimeout(() => {
        asyncRef.current += 1
        void handleSearch(value)
      }, 350)
    },
    [handleSearch],
  )

  const handleLoadMore = useCallback(() => {
    if (!hasMore || nextOffset == null || searchingRef.current) return
    void handleSearch(query, nextOffset, true)
  }, [handleSearch, hasMore, nextOffset, query])

  const handleSelectSeries = useCallback((series: ComicVineSeriesResult) => {
    setSelectedSeries(series)
    setUncheckedRowIds(new Set())
    commit.reset()
    setStep('preview')
  }, [commit])

  const handleBackToSearch = useCallback(() => {
    setStep('search')
    setSelectedSeries(null)
    commit.reset()
  }, [commit])

  const rows = useMemo(() => preview.data?.rows ?? [], [preview.data])
  const ownedRows = useMemo(() => rows.filter(isOwnedSeriesMappingRow), [rows])
  const approvableRows = useMemo(() => bulkApprovableSeriesMappingRows(rows), [rows])
  const providerInventoryCount = rows.length - ownedRows.length

  const selectedRowIds = useMemo(
    () =>
      approvableRows
        .filter((row) => row.default_selected && !uncheckedRowIds.has(row.row_id))
        .map((row) => row.row_id),
    [approvableRows, uncheckedRowIds],
  )

  // The preview token is unique per preview and already embeds its issue time, so
  // deriving the key from it keeps one idempotency key across retries of the same
  // approval while a re-read preview naturally produces a fresh one.
  const previewToken = preview.data?.preview_token ?? null
  const idempotencyKey =
    previewToken && originIssueId != null
      ? `queue-mapping-${threadId}-${originIssueId}-${preview.data?.issued_at ?? 0}`
      : null

  const commitErrorDetail = commit.isError ? getApiErrorDetail(commit.error) : null
  const previewIsStale = commitErrorDetail !== null && STALE_PREVIEW_DETAILS.has(commitErrorDetail)

  const commitMessage = (() => {
    if (!commit.isError) return null
    if (previewIsStale) return 'That preview is out of date. Reviewing the series again.'
    return 'Could not map the series. Nothing was changed.'
  })()

  const toggleRow = (rowId: string, checked: boolean) => {
    setUncheckedRowIds((previous) => {
      const next = new Set(previous)
      if (checked) {
        next.delete(rowId)
      } else {
        next.add(rowId)
      }
      return next
    })
  }

  const approveSelected = () => {
    if (!previewToken || !idempotencyKey || selectedRowIds.length === 0) return
    commit.mutate(
      {
        preview_token: previewToken,
        idempotency_key: idempotencyKey,
        approved_row_ids: selectedRowIds,
      },
      {
        onSuccess: (result) => {
          onMapped(result.confirmed_issue_ids)
        },
        onError: (error) => {
          // A stale or expired preview cannot be re-committed, so re-read the plan
          // instead of leaving the reader with a dead approval.
          if (STALE_PREVIEW_DETAILS.has(getApiErrorDetail(error))) {
            commit.reset()
            setUncheckedRowIds(new Set())
            void preview.refetch()
          }
        },
      },
    )
  }

  const dialogTitle = step === 'search' ? 'Map Series' : 'Review Series Mapping'

  return (
    <Modal isOpen={isOpen} title={dialogTitle} onClose={onClose} size="large">
      <div data-testid="queue-map-series-dialog">
        {step === 'search' && (
          <div className="space-y-4">
            <p className="text-sm text-stone-300">
              Find the ComicVine volume for{' '}
              <span className="font-bold text-stone-100">{threadTitle}</span>. Nothing changes
              until you review and approve the mapping plan.
            </p>
            <input
              type="search"
              value={query}
              onChange={(event) => handleQueryChange(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && query.trim()) {
                  if (debounceRef.current) clearTimeout(debounceRef.current)
                  void handleSearch(query)
                }
              }}
              placeholder="Search ComicVine volumes"
              aria-label="Search ComicVine volumes"
              data-testid="queue-map-series-search-input"
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
                      data-testid="queue-map-series-result"
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
                data-testid="queue-map-series-load-more"
                className="w-full min-h-11 rounded-xl px-4 text-sm font-bold text-stone-200 bg-stone-800/60 border border-stone-700/50 hover:bg-stone-800 transition disabled:opacity-50"
              >
                {isSearching ? 'Loading...' : 'Show more volumes'}
              </button>
            )}
          </div>
        )}

        {step === 'preview' && selectedSeries && (
          <div className="space-y-4" data-testid="queue-map-series-preview">
            <p className="text-sm text-stone-300">
              Mapping plan for{' '}
              <span className="font-bold text-stone-100">{selectedSeries.name}</span>. Only exact
              matches are selected; review-needed rows stay untouched.
            </p>
            <button
              type="button"
              onClick={handleBackToSearch}
              data-testid="queue-map-series-back"
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
                <button
                  type="button"
                  onClick={onClose}
                  data-testid="queue-map-series-dismiss"
                  className="w-full min-h-11 rounded-xl px-4 text-sm font-bold text-stone-200 bg-stone-800/60 border border-stone-700/50 hover:bg-stone-800 transition"
                >
                  Done
                </button>
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
                  data-testid="queue-map-series-dismiss"
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

                {commitMessage && (
                  <p
                    role="alert"
                    className="rounded-lg bg-rose-900/30 border border-rose-700/40 p-3 text-sm text-rose-200"
                  >
                    {commitMessage}
                  </p>
                )}

                {approvableRows.length === 0 && !commit.isSuccess && (
                  <p className="rounded-lg bg-stone-800/40 border border-stone-700/50 p-3 text-sm text-stone-300">
                    No exact matches for your issues in this volume. Ambiguous and special rows
                    are never mapped automatically.
                  </p>
                )}

                <ul className="space-y-2 max-h-72 overflow-y-auto overscroll-contain">
                  {ownedRows.map((row) => {
                    const isApprovable = approvableRows.some(
                      (candidate) => candidate.row_id === row.row_id,
                    )
                    const checkboxId = `queue-map-series-${row.row_id}`
                    return (
                      <li
                        key={row.row_id}
                        data-testid="queue-map-series-row"
                        data-classification={row.classification}
                        className="flex items-center gap-3 rounded-xl bg-stone-800/50 border border-stone-700/50 p-3"
                      >
                        {isApprovable && !commit.isSuccess ? (
                          <input
                            id={checkboxId}
                            type="checkbox"
                            className="h-5 w-5 shrink-0 accent-amber-500"
                            checked={selectedRowIds.includes(row.row_id)}
                            onChange={(event) => toggleRow(row.row_id, event.target.checked)}
                          />
                        ) : (
                          <span aria-hidden="true" className="h-5 w-5 shrink-0" />
                        )}
                        <label
                          htmlFor={isApprovable && !commit.isSuccess ? checkboxId : undefined}
                          className="min-w-0 flex-1 text-sm text-stone-100"
                        >
                          <span className="font-bold">{issueNumberLabel(row)}</span>
                          {row.title ? <span className="text-stone-300"> {row.title}</span> : null}
                        </label>
                        <span
                          className={`shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-black uppercase tracking-wider ${STATUS_ACCENT_CLASS[row.classification]}`}
                        >
                          {STATUS_LABEL[row.classification]}
                        </span>
                      </li>
                    )
                  })}
                </ul>

                {providerInventoryCount > 0 && (
                  <p
                    className="text-xs text-stone-500"
                    data-testid="queue-map-series-provider-inventory"
                  >
                    {providerInventoryCount} other{' '}
                    {providerInventoryCount === 1 ? 'issue is' : 'issues are'} in this volume but
                    not in your library.
                  </p>
                )}

                <div className="flex flex-col gap-2 sm:flex-row">
                  <button
                    type="button"
                    onClick={onClose}
                    disabled={commit.isPending}
                    data-testid="queue-map-series-dismiss"
                    className="min-h-11 flex-1 rounded-xl px-4 text-sm font-bold text-stone-200 bg-stone-800/60 border border-stone-700/50 hover:bg-stone-800 transition disabled:opacity-50"
                  >
                    {commit.isSuccess ? 'Done' : 'Cancel'}
                  </button>
                  {!commit.isSuccess && (
                    <button
                      type="button"
                      onClick={approveSelected}
                      disabled={commit.isPending || selectedRowIds.length === 0}
                      data-testid="queue-map-series-approve"
                      className="min-h-11 flex-1 rounded-xl px-4 text-sm font-bold text-stone-900 bg-amber-500 hover:bg-amber-400 transition disabled:opacity-50"
                    >
                      {commit.isPending
                        ? 'Mapping...'
                        : `Map ${selectedRowIds.length} ${selectedRowIds.length === 1 ? 'issue' : 'issues'}`}
                    </button>
                  )}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </Modal>
  )
}
