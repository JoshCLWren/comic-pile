import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import Modal from './Modal'
import { comicVineApi } from '../services/api-comicvine'
import type { ComicVineSeriesResult } from '../services/api-comicvine'
import { issuesApi } from '../services/api-issues'
import {
  bulkApprovableSeriesMappingRows,
  isOwnedSeriesMappingRow,
} from '../services/api-series-mapping'
import type {
  SeriesMappingClassification,
  SeriesMappingPreviewRow,
} from '../services/api-series-mapping'
import {
  useCommitSeriesMapping,
  useSiblingSeriesMappingPreview,
} from '../hooks/useSiblingSeriesMapping'
import { invalidateAfterQueueMutation } from '../query/cacheEffects'
import { queryClient } from '../query/queryClient'
import { queryKeys } from '../query/queryKeys'
import { getApiErrorDetail } from '../utils/apiError'
import type { ThreadListItem } from '../types'

interface QueueMapSeriesDialogProps {
  /** Queue row being repaired. The dialog mounts only while this is non-null. */
  thread: ThreadListItem
  /** Closes the dialog. Canceling never mutates Queue order, progress, or issues. */
  onClose: () => void
}

const SEARCH_PAGE_SIZE = 10
const ANCHOR_ISSUE_PAGE_SIZE = 50

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

function seriesMetaText(series: ComicVineSeriesResult): string {
  // SAFETY: All ComicVine series results have optional string fields
  const parts: string[] = []
  if (series.publisher) parts.push(series.publisher)
  if (series.start_year) parts.push(`${series.start_year}`)
  if (series.issue_count) parts.push(`${series.issue_count} issues`)
  return parts.join(' · ')
}

function rowIssueLabel(row: SeriesMappingPreviewRow): string {
  return row.issue_number ? `#${row.issue_number}` : 'Unnumbered'
}

function newIdempotencyKey(): string {
  // SAFETY: Check for crypto API availability at runtime
  const hasModernCrypto = typeof crypto !== 'undefined' && 'randomUUID' in crypto
  if (hasModernCrypto) {
    return `queue-map-series-${crypto.randomUUID()}`
  }
  return `queue-map-series-${Date.now()}-${Math.floor(Math.random() * Number.MAX_SAFE_INTEGER)}`
}

/**
 * Queue entry point for ComicVine series repair (issue #2773).
 *
 * The Queue row itself renders from the persisted #2776 projection with no
 * per-card fetch and no live provider request. Provider traffic starts only
 * here, once the reader opens the flow: pick the provider volume with the
 * shared ComicVine series search, review the read-only #2721 preview
 * classifications/counts, then approve safe exact rows for the transactional
 * idempotent #2722 commit. Ambiguous, conflicting, unresolved, and special
 * rows are reported and stay untouched for issue-level correction.
 *
 * A successful commit invalidates the Queue pages so the row indicator
 * refreshes without a hard reload. Canceling or failing changes nothing.
 */
export default function QueueMapSeriesDialog({ thread, onClose }: QueueMapSeriesDialogProps) {
  const [query, setQuery] = useState(thread.title)
  const [seriesResults, setSeriesResults] = useState<ComicVineSeriesResult[]>([])
  const [selectedSeries, setSelectedSeries] = useState<ComicVineSeriesResult | null>(null)
  const [hasMore, setHasMore] = useState(false)
  const [nextOffset, setNextOffset] = useState<number | null>(null)
  const [isSearching, setIsSearching] = useState(false)
  const [searchError, setSearchError] = useState<string | null>(null)
  const [hasSearched, setHasSearched] = useState(false)
  const [uncheckedRowIds, setUncheckedRowIds] = useState<ReadonlySet<string>>(() => new Set())
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const asyncRef = useRef(0)

  useEffect(() => {
    return () => {
      if (debounceRef.current) {
        clearTimeout(debounceRef.current)
        debounceRef.current = null
      }
    }
  }, [])

  // Anchor the #2721 preview on one owned issue: the next unread issue when it
  // can be matched, otherwise the first unread issue, otherwise the first
  // issue. The anchor licenses scope; it is not itself proof of series scope.
  const anchorIssues = useQuery({
    queryKey: queryKeys.thread.issuePage(thread.id, {
      pageToken: null,
      pageSize: ANCHOR_ISSUE_PAGE_SIZE,
    }),
    queryFn: () => issuesApi.list(thread.id, { page_size: ANCHOR_ISSUE_PAGE_SIZE }),
  })

  const anchorIssueId = useMemo(() => {
    const issues = anchorIssues.data?.issues ?? []
    if (issues.length === 0) return null
    const nextUnread = thread.next_unread_issue_number?.trim()
    if (nextUnread) {
      const match = issues.find((issue) => issue.issue_number.trim() === nextUnread)
      if (match) return match.id
    }
    return issues.find((issue) => issue.status === 'unread')?.id ?? issues[0]?.id ?? null
  }, [anchorIssues.data, thread.next_unread_issue_number])

  const runSearch = useCallback(async (searchQuery: string, offset = 0, append = false) => {
    if (!searchQuery.trim()) {
      setSeriesResults([])
      setHasSearched(false)
      setHasMore(false)
      setNextOffset(null)
      return
    }
    const requestId = ++asyncRef.current
    setIsSearching(true)
    setSearchError(null)
    setHasSearched(true)
    try {
      const response = await comicVineApi.searchSeries(searchQuery.trim(), SEARCH_PAGE_SIZE, offset)
      if (requestId !== asyncRef.current) return
      setSeriesResults((previous) => {
        if (!append) return response.results
        const seen = new Set(previous.map((series) => series.comicvine_volume_id))
        return [...previous, ...response.results.filter((series) => {
          if (seen.has(series.comicvine_volume_id)) return false
          seen.add(series.comicvine_volume_id)
          return true
        })]
      })
      setHasMore(response.has_more)
      setNextOffset(response.next_offset)
    } catch {
      if (requestId !== asyncRef.current) return
      setSearchError('Failed to search ComicVine. Please try again.')
      if (!append) setSeriesResults([])
    } finally {
      if (requestId === asyncRef.current) setIsSearching(false)
    }
  }, [])

  // Auto-search the thread title once when the dialog opens so the reader
  // lands on candidate volumes instead of an empty box.
  const autoSearchedRef = useRef(false)
  useEffect(() => {
    if (!autoSearchedRef.current && thread.title.trim()) {
      autoSearchedRef.current = true
      void runSearch(thread.title)
    }
  }, [thread.title, runSearch])

  const handleQueryChange = (value: string) => {
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
      void runSearch(value)
    }, 350)
  }

  const previewEnabled = selectedSeries !== null && anchorIssueId !== null
  const preview = useSiblingSeriesMappingPreview(
    anchorIssueId,
    'comicvine',
    selectedSeries ? String(selectedSeries.comicvine_volume_id) : null,
    previewEnabled,
  )
  const commit = useCommitSeriesMapping()

  // One idempotency key per selected volume: retries of the same approval
  // reuse it, while picking a different volume starts a fresh key so the
  // commit surface never sees a reused key with materially different input.
  const idempotencyKey = useMemo(
    () => (selectedSeries ? newIdempotencyKey() : null),
    [selectedSeries],
  )

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

  const toggleRow = (rowId: string, checked: boolean) => {
    setUncheckedRowIds((previous) => {
      const next = new Set(previous)
      if (checked) next.delete(rowId)
      else next.add(rowId)
      return next
    })
  }

  const approveSelected = () => {
    const previewToken = preview.data?.preview_token
    if (!previewToken || !idempotencyKey || selectedRowIds.length === 0) return
    commit.mutate(
      {
        preview_token: previewToken,
        idempotency_key: idempotencyKey,
        approved_row_ids: selectedRowIds,
      },
      {
        onSuccess: () => {
          // Refresh the Queue pages so the mapping indicator updates without
          // a hard reload. Order, progress, ratings, and dependencies are
          // untouched: the commit only confirms issue identities.
          void invalidateAfterQueueMutation(queryClient)
        },
      },
    )
  }

  const backToSeries = () => {
    setSelectedSeries(null)
    setUncheckedRowIds(new Set())
    commit.reset()
  }

  const dialogTitle = commit.isSuccess
    ? 'Series mapped'
    : selectedSeries ? 'Review mappings' : `Map ${thread.title}`

  return (
    <Modal isOpen title={dialogTitle} onClose={onClose} size="large" data-testid="queue-map-series-dialog">
      <div className="space-y-4">
        {selectedSeries === null && (
          <>
            <p className="text-sm text-[var(--theme-text-muted)]">
              Search for the correct ComicVine series for{' '}
              <span className="font-bold text-[var(--theme-text-primary)]">{thread.title}</span>.
              No series is linked until you review and approve the mapping.
            </p>
            <div className="relative">
              <input
                type="text"
                value={query}
                onChange={(event) => handleQueryChange(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' && query.trim()) {
                    if (debounceRef.current) clearTimeout(debounceRef.current)
                    void runSearch(query)
                  }
                }}
                placeholder="Search ComicVine series"
                aria-label="Search ComicVine series"
                className="min-h-11 w-full rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-4 pr-10 text-sm text-[var(--theme-text-primary)] outline-none transition focus:border-[var(--theme-focus-ring)]"
              />
              {isSearching && (
                <div className="absolute top-1/2 right-3 -translate-y-1/2">
                  <div className="h-4 w-4 animate-spin rounded-full border-2 border-[var(--theme-comic-accent)]/30 border-t-[var(--theme-comic-accent)]" />
                </div>
              )}
            </div>
            {searchError && (
              <p role="alert" className="rounded-lg border border-[var(--theme-danger)]/40 bg-[var(--theme-danger)]/10 p-3 text-sm text-[var(--theme-text-primary)]">
                {searchError}
              </p>
            )}
            {seriesResults.length > 0 && (
              <div className="max-h-96 space-y-2 overflow-y-auto overscroll-contain">
                {seriesResults.map((series) => (
                  <button
                    key={series.comicvine_volume_id}
                    type="button"
                    onClick={() => setSelectedSeries(series)}
                    aria-label={series.name}
                    className="w-full rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] p-3 text-left transition hover:border-[var(--theme-comic-accent)]/50"
                  >
                    <p className="truncate text-sm font-bold text-[var(--theme-text-primary)]">
                      {series.name}
                    </p>
                    {seriesMetaText(series) && (
                      <p className="text-sm font-medium text-[var(--theme-text-muted)]">
                        {seriesMetaText(series)}
                      </p>
                    )}
                  </button>
                ))}
                {hasMore && nextOffset !== null && (
                  <button
                    type="button"
                    onClick={() => void runSearch(query, nextOffset, true)}
                    disabled={isSearching}
                    data-testid="queue-map-series-load-more"
                    className="min-h-11 w-full rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-4 text-sm font-bold text-[var(--theme-text-primary)] transition disabled:opacity-50"
                  >
                    {isSearching ? 'Loading...' : 'Load more'}
                  </button>
                )}
              </div>
            )}
            {!isSearching && hasSearched && seriesResults.length === 0 && !searchError && (
              <p className="py-4 text-center text-sm text-[var(--theme-text-muted)]">
                No series found. Try a different search term.
              </p>
            )}
            <div className="flex flex-col gap-2 sm:flex-row">
              <button
                type="button"
                onClick={onClose}
                data-testid="queue-map-series-cancel"
                className="min-h-11 flex-1 rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-4 text-sm font-bold text-[var(--theme-text-muted)] transition hover:text-[var(--theme-text-primary)]"
              >
                Cancel
              </button>
            </div>
          </>
        )}

        {selectedSeries !== null && (
          <>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={backToSeries}
                disabled={commit.isPending}
                className="text-sm font-bold text-[var(--theme-comic-accent)] hover:text-[var(--theme-text-primary)] disabled:opacity-50"
              >
                ← Back to search
              </button>
              <span className="text-xs text-[var(--theme-text-dim)]">·</span>
              <span className="truncate text-sm text-[var(--theme-text-muted)]">
                {selectedSeries.name}
                {seriesMetaText(selectedSeries) && ` (${seriesMetaText(selectedSeries)})`}
              </span>
            </div>

            {anchorIssues.isPending && (
              <div className="flex justify-center py-8" data-testid="queue-map-series-anchor-loading">
                <div className="h-5 w-5 animate-spin rounded-full border-2 border-[var(--theme-comic-accent)]/30 border-t-[var(--theme-comic-accent)]" />
              </div>
            )}

            {anchorIssues.isError && (
              <>
                <p role="alert" className="rounded-lg border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] p-3 text-sm text-[var(--theme-text-muted)]">
                  This series could not be read, so there is nothing safe to map yet.
                </p>
                <button
                  type="button"
                  onClick={onClose}
                  data-testid="queue-map-series-cancel"
                  className="min-h-11 w-full rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-4 text-sm font-bold text-[var(--theme-text-muted)] transition hover:text-[var(--theme-text-primary)]"
                >
                  Close
                </button>
              </>
            )}

            {anchorIssues.isSuccess && anchorIssueId === null && (
              <>
                <p className="rounded-lg border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] p-3 text-sm text-[var(--theme-text-muted)]">
                  {thread.title} does not use issue tracking, so there is no mapping to repair.
                </p>
                <button
                  type="button"
                  onClick={onClose}
                  data-testid="queue-map-series-cancel"
                  className="min-h-11 w-full rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-4 text-sm font-bold text-[var(--theme-text-muted)] transition hover:text-[var(--theme-text-primary)]"
                >
                  Close
                </button>
              </>
            )}

            {anchorIssues.isSuccess && anchorIssueId !== null && preview.isPending && (
              <div className="space-y-4" data-testid="queue-map-series-preview-loading">
                <p className="text-sm text-[var(--theme-text-muted)]">
                  Checking <span className="font-bold text-[var(--theme-text-primary)]">{selectedSeries.name}</span> for
                  exact matches. Nothing is linked yet.
                </p>
                <div className="flex justify-center py-6">
                  <div className="h-5 w-5 animate-spin rounded-full border-2 border-[var(--theme-comic-accent)]/30 border-t-[var(--theme-comic-accent)]" />
                </div>
              </div>
            )}

            {anchorIssues.isSuccess && anchorIssueId !== null && preview.isError && (
              <>
                <p role="alert" data-testid="queue-map-series-preview-error" className="rounded-lg border border-[var(--theme-danger)]/40 bg-[var(--theme-danger)]/10 p-3 text-sm text-[var(--theme-text-primary)]">
                  The mapping preview failed ({getApiErrorDetail(preview.error)}). Nothing was
                  changed. Queue order, progress, ratings, and dependencies are untouched.
                </p>
                <div className="flex flex-col gap-2 sm:flex-row">
                  <button
                    type="button"
                    onClick={onClose}
                    data-testid="queue-map-series-cancel"
                    className="min-h-11 flex-1 rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-4 text-sm font-bold text-[var(--theme-text-muted)] transition hover:text-[var(--theme-text-primary)]"
                  >
                    Close
                  </button>
                  <button
                    type="button"
                    onClick={() => void preview.refetch()}
                    data-testid="queue-map-series-retry"
                    className="min-h-11 flex-1 rounded-xl bg-[var(--theme-primary-action)] px-4 text-sm font-bold text-stone-950 transition hover:bg-[var(--theme-primary-action-hover)]"
                  >
                    Try again
                  </button>
                </div>
              </>
            )}

            {anchorIssues.isSuccess && anchorIssueId !== null && preview.isSuccess && preview.data.scope.status === 'unavailable' && (
              <>
                <p data-testid="queue-map-series-unavailable" className="rounded-lg border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] p-3 text-sm text-[var(--theme-text-muted)]">
                  {selectedSeries.name} cannot be safely bulk-mapped to this series yet. No
                  mappings were offered and nothing changed; individual issues can still be
                  corrected from their issue details.
                </p>
                <button
                  type="button"
                  onClick={onClose}
                  data-testid="queue-map-series-cancel"
                  className="min-h-11 w-full rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-4 text-sm font-bold text-[var(--theme-text-muted)] transition hover:text-[var(--theme-text-primary)]"
                >
                  Close
                </button>
              </>
            )}

            {anchorIssues.isSuccess && anchorIssueId !== null && preview.isSuccess && preview.data.scope.status === 'available' && !commit.isSuccess && (
              <section aria-label="Mapping preview" className="space-y-3" data-testid="queue-map-series-preview">
                <p className="text-sm text-[var(--theme-text-muted)]">
                  <span className="font-bold text-[var(--theme-text-primary)]">{selectedSeries.name}</span>{' '}
                  matches {approvableRows.length}{' '}
                  {approvableRows.length === 1 ? 'issue' : 'issues'} exactly. Only exact
                  matches are preselected; everything else stays untouched.
                </p>

                {commit.isError && (
                  <p role="alert" data-testid="queue-map-series-commit-error" className="rounded-lg border border-[var(--theme-danger)]/40 bg-[var(--theme-danger)]/10 p-3 text-sm text-[var(--theme-text-primary)]">
                    Could not map the selected issues ({getApiErrorDetail(commit.error)}).
                    Nothing was partially changed.
                  </p>
                )}

                {approvableRows.length === 0 ? (
                  <p className="rounded-lg border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] p-3 text-sm text-[var(--theme-text-muted)]">
                    No issue in this series matches {selectedSeries.name} by number exactly, so
                    there is nothing safe to map in bulk.
                  </p>
                ) : (
                  <ul className="max-h-72 space-y-2 overflow-y-auto overscroll-contain">
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
                          className="flex items-center gap-3 rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] p-3"
                        >
                          {isApprovable ? (
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
                            htmlFor={isApprovable ? checkboxId : undefined}
                            className="min-w-0 flex-1 text-sm text-[var(--theme-text-primary)]"
                          >
                            <span className="font-bold">{rowIssueLabel(row)}</span>
                            {row.title ? <span className="text-[var(--theme-text-muted)]"> {row.title}</span> : null}
                          </label>
                          <span
                            className={`shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-black tracking-wider uppercase ${STATUS_ACCENT_CLASS[row.classification]}`}
                          >
                            {STATUS_LABEL[row.classification]}
                          </span>
                        </li>
                      )
                    })}
                  </ul>
                )}

                {providerInventoryCount > 0 && (
                  <p className="text-xs text-[var(--theme-text-dim)]" data-testid="queue-map-series-provider-inventory">
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
                    data-testid="queue-map-series-cancel"
                    className="min-h-11 flex-1 rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-4 text-sm font-bold text-[var(--theme-text-muted)] transition hover:text-[var(--theme-text-primary)] disabled:opacity-50"
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    onClick={approveSelected}
                    disabled={commit.isPending || selectedRowIds.length === 0}
                    data-testid="queue-map-series-approve"
                    className="min-h-11 flex-1 rounded-xl bg-[var(--theme-primary-action)] px-4 text-sm font-bold text-stone-950 transition hover:bg-[var(--theme-primary-action-hover)] disabled:opacity-50"
                  >
                    {commit.isPending
                      ? 'Mapping...'
                      : `Map ${selectedRowIds.length} ${selectedRowIds.length === 1 ? 'issue' : 'issues'}`}
                  </button>
                </div>
              </section>
            )}

            {anchorIssues.isSuccess && anchorIssueId !== null && preview.isSuccess && preview.data.scope.status === 'available' && commit.isSuccess && (
              <section aria-label="Mapping result" className="space-y-3" data-testid="queue-map-series-result">
                <p role="status" className="rounded-lg border border-[var(--theme-primary-action)]/40 bg-[var(--theme-bg-panel)] p-3 text-sm text-[var(--theme-text-primary)]">
                  {commit.data.confirmed_issue_ids.length}{' '}
                  {commit.data.confirmed_issue_ids.length === 1 ? 'issue' : 'issues'} mapped to{' '}
                  {selectedSeries.name}.
                  {commit.data.needs_review_issue_ids.length > 0 && (
                    <>
                      {' '}{commit.data.needs_review_issue_ids.length} still{' '}
                      {commit.data.needs_review_issue_ids.length === 1 ? 'needs' : 'need'} review
                      and {commit.data.needs_review_issue_ids.length === 1 ? 'is' : 'are'} available
                      for issue-level correction.
                    </>
                  )}
                </p>
                <button
                  type="button"
                  onClick={onClose}
                  data-testid="queue-map-series-done"
                  className="min-h-11 w-full rounded-xl bg-[var(--theme-primary-action)] px-4 text-sm font-bold text-stone-950 transition hover:bg-[var(--theme-primary-action-hover)]"
                >
                  Done
                </button>
              </section>
            )}
          </>
        )}
      </div>
    </Modal>
  )
}
