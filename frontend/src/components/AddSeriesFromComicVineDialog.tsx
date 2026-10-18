import { useState, useCallback, useRef, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import Modal from './Modal'
import { comicVineApi } from '../services/api-comicvine'
import type {
  ComicVineSeriesImportStatus,
  ComicVineSeriesResult,
  ComicVineSeriesSearchResponse,
  ComicVineImportSeriesPayload,
  ComicVineImportSeriesResult,
} from '../services/api-comicvine'
import ImageWithLoading from './ImageWithLoading'
import { optimizedImageUrl, optimizedImageSrcSet } from '../services/imageDelivery'
import { useToast } from '../contexts/useToast'
import { queryClient } from '../query/queryClient'
import { invalidateAfterQueueMutation } from '../query/cacheEffects'
import { getApiErrorDetail, getApiErrorStatus } from '../utils/apiError'
import { queryKeys } from '../query/queryKeys'

interface AddSeriesFromComicVineDialogProps {
  isOpen: boolean
  onClose: () => void
  onAdded: (threadId: number) => void
}

type DialogStep = 'search' | 'select-series' | 'confirm'

const SEARCH_PAGE_SIZE = 10

const EMPTY_PAGINATION = {
  offset: 0,
  limit: SEARCH_PAGE_SIZE,
  hasMore: false,
  // SAFETY: null is the correct initial value for an optional number field
  nextOffset: null as number | null,
}

function seriesMetaParts(series: ComicVineSeriesResult): string[] {
  return [
    series.publisher,
    series.start_year ? `${series.start_year}` : null,
    series.issue_count ? `${series.issue_count} issues` : null,
  ].filter((part): part is string => part !== null)
}

function seriesMetaText(series: ComicVineSeriesResult): string {
  return seriesMetaParts(series).join(' · ')
}

function seriesAccessibleName(series: ComicVineSeriesResult): string {
  const parts = seriesMetaParts(series)
  return parts.length > 0 ? `${series.name} - ${parts.join(', ')}` : series.name
}

function mergeSeriesResults(
  previous: ComicVineSeriesResult[],
  incoming: ComicVineSeriesResult[],
): ComicVineSeriesResult[] {
  const seen = new Set(previous.map((series) => series.comicvine_volume_id))
  const merged = previous.slice()
  for (const series of incoming) {
    if (!seen.has(series.comicvine_volume_id)) {
      seen.add(series.comicvine_volume_id)
      merged.push(series)
    }
  }
  return merged
}

function paginationFromResponse(response: {
  offset: number
  limit: number
  has_more: boolean
  next_offset: number | null
}) {
  return {
    offset: response.offset || 0,
    limit: response.limit || 10,
    hasMore: response.has_more || false,
    nextOffset: response.next_offset || null,
  }
}

/** A completed import, whether the client heard the response or recovered it. */
interface ImportOutcome {
  threadId: number
  seriesName: string
  /** Issues now tracked by the series, or null when the server did not say. */
  issuesAdopted: number | null
  /** False when the add reused an existing series instead of creating one. */
  threadCreated: boolean
}

/**
 * Describe a completed import.
 *
 * A recovered import learned its issue count from the status endpoint, which
 * reports the server's tracked count rather than how many rows this particular
 * request adopted, so a null count drops the parenthetical instead of
 * inventing "0 issues".
 */
function importSuccessMessage({ seriesName, issuesAdopted, threadCreated }: ImportOutcome, result?: ComicVineImportSeriesResult): string {
  if (issuesAdopted === null) {
    return `Added "${seriesName}" to ComicPile`
  }
  if (!threadCreated && issuesAdopted === 0) {
    // Check for conflicts or errors that occurred during import
    if (result && result.issues_conflict > 0) {
      return `"${seriesName}" imported with ${result.issues_conflict} conflicts - check your queue for details`
    }
    const hasErrors = result?.issue_results?.some((issue) => issue.outcome === 'error') ?? false
    if (hasErrors) {
      return `"${seriesName}" imported but some issues couldn't be added - check your queue for details`
    }
    return `"${seriesName}" is already up to date`
  }
  return threadCreated
    ? `Added "${seriesName}" to ComicPile (${issuesAdopted} issues)`
    : `Added ${issuesAdopted} more issues to "${seriesName}"`
}

/**
 * Ask the server whether one ComicVine volume actually reached the queue.
 *
 * Returns null both when the volume is not imported and when the check itself
 * fails: either way the client cannot prove the import failed.
 */
async function readCommittedImport(volumeId: number): Promise<ComicVineSeriesImportStatus | null> {
  try {
    const status = await comicVineApi.getSeriesImportStatus(volumeId)
    return status?.imported ? status : null
  } catch {
    return null
  }
}

/** True for a failure the server never answered, so its outcome is unknown. */
function hasUnknownOutcome(error: unknown): boolean {
  return error instanceof Error && getApiErrorStatus(error) === null
}

export default function AddSeriesFromComicVineDialog({
  isOpen,
  onClose,
  onAdded,
}: AddSeriesFromComicVineDialogProps) {
  const { showToast } = useToast()

  const [step, setStep] = useState<DialogStep>('search')
  const [query, setQuery] = useState('')
  const [seriesResults, setSeriesResults] = useState<ComicVineSeriesResult[]>([])
  const [selectedSeries, setSelectedSeries] = useState<ComicVineSeriesResult | null>(null)
  const [pagination, setPagination] = useState(EMPTY_PAGINATION)
  const [isSearching, setIsSearching] = useState(false)
  const [isAdding, setIsAdding] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [unknownOutcome, setUnknownOutcome] = useState<string | null>(null)
  const [hasSearched, setHasSearched] = useState(false)
  const [alreadyReadCount, setAlreadyReadCount] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const asyncRef = useRef(0)
  const searchingRef = useRef(false)

  useEffect(() => {
    return () => {
      if (debounceRef.current) {
        clearTimeout(debounceRef.current)
        debounceRef.current = null
      }
    }
  }, [])

  useEffect(() => {
    if (isOpen) {
      setStep('search')
      setQuery('')
      setSeriesResults([])
      setSelectedSeries(null)
      setPagination(EMPTY_PAGINATION)
      setError(null)
      setUnknownOutcome(null)
      setHasSearched(false)
      setAlreadyReadCount(0)
    }
  }, [isOpen])

  /**
   * Ask the server whether the selected volume is already linked (#3854).
   *
   * `getSeriesImportStatus` is the same user-scoped answer the lost-response
   * recovery trusts, so the confirm copy can tell an existing series from a
   * fresh add without waiting on the paginated queue. An unreachable check
   * keeps the fresh-add copy; the import itself stays idempotent server-side,
   * so a stale "new series" fallback never creates a duplicate row.
   */
  const selectedVolumeId = selectedSeries?.comicvine_volume_id
  const { data: existingSeries } = useQuery({
    queryKey: selectedVolumeId != null ? queryKeys.comicVine.importStatus(selectedVolumeId) : [],
    queryFn: () => comicVineApi.getSeriesImportStatus(selectedVolumeId!),
    enabled: isOpen && step === 'confirm' && selectedVolumeId != null,
    retry: false,
    // The status endpoint answers for every volume; only an `imported` volume
    // means the confirm copy should say "already in your queue".
    select: (status) => (status?.imported ? status : null),
  })

  const handleSearch = useCallback(
    async (searchQuery: string, offset = 0, append = false) => {
      if (!searchQuery.trim()) {
        setSeriesResults([])
        setHasSearched(false)
        setPagination(EMPTY_PAGINATION)
        return
      }
      const requestId = ++asyncRef.current
      searchingRef.current = true
      setIsSearching(true)
      setError(null)
      setHasSearched(true)
      try {
        const response = await comicVineApi.searchSeries(searchQuery.trim(), SEARCH_PAGE_SIZE, offset)
        if (requestId !== asyncRef.current) return
        if (!response?.results) {
          setError('Invalid response from ComicVine. Please try again.')
          setSeriesResults((previous) => (append ? previous : []))
          return
        }
        setSeriesResults((previous) =>
          append ? mergeSeriesResults(previous, response.results) : response.results,
        )
        setPagination(paginationFromResponse(response))
      } catch {
        if (requestId !== asyncRef.current) return
        setError('Failed to search ComicVine. Please try again.')
        setSeriesResults((previous) => (append ? previous : []))
      } finally {
        if (requestId === asyncRef.current) {
          setIsSearching(false)
          searchingRef.current = false
        }
      }
    },
    [],
  )

  const handleQueryChange = useCallback(
    (value: string) => {
      setQuery(value)
      if (debounceRef.current) clearTimeout(debounceRef.current)
      if (!value.trim()) {
        setHasSearched(false)
        setSeriesResults([])
        setPagination(EMPTY_PAGINATION)
        return
      }
      debounceRef.current = setTimeout(() => {
        asyncRef.current += 1
        handleSearch(value)
      }, 350)
    },
    [handleSearch],
  )

  const handleLoadMore = useCallback(() => {
    if (!pagination.hasMore || pagination.nextOffset == null || searchingRef.current) return
    handleSearch(query, pagination.nextOffset, true)
  }, [pagination, query, handleSearch])

  const handleSelectSeries = useCallback((series: ComicVineSeriesResult) => {
    setSelectedSeries(series)
    // Personal read progress belongs to one specific series. Selecting a
    // different run must not carry the previous volume's already-read count
    // into the new confirmation, where it would exceed the new issue count.
    setAlreadyReadCount(0)
    setStep('confirm')
  }, [])

  const finishAdd = useCallback(
    async (outcome: ImportOutcome, result?: ComicVineImportSeriesResult) => {
      showToast(importSuccessMessage(outcome, result), 'success')
      await invalidateAfterQueueMutation(queryClient)
      onAdded(outcome.threadId)
      onClose()
    },
    [onAdded, onClose, showToast],
  )

  const handleAdd = useCallback(async () => {
    if (!selectedSeries) return
    const volumeId = selectedSeries.comicvine_volume_id
    const seriesName = selectedSeries.name
    setIsAdding(true)
    setError(null)
    setUnknownOutcome(null)
    try {
      const payload: ComicVineImportSeriesPayload = {
        comicvine_volume_id: volumeId,
        already_read_count: alreadyReadCount,
      }
      const result = await comicVineApi.importSeries(payload)
      await finishAdd({
        threadId: result.thread_id,
        seriesName: result.series_name,
        issuesAdopted: result.issues_adopted,
        threadCreated: result.thread_created,
      }, result)
    } catch (err: unknown) {
      // An import that outlives the client budget keeps running server-side and
      // commits after the client gives up, so a request the server never
      // answered proves nothing (#3445). Ask the server what actually happened
      // before reporting an error the user would answer with a duplicate retry.
      if (hasUnknownOutcome(err)) {
        const committed = await readCommittedImport(volumeId)
        if (committed?.thread_id != null) {
          await finishAdd({
            threadId: committed.thread_id,
            seriesName: committed.series_name ?? seriesName,
            issuesAdopted: committed.issue_count,
            threadCreated: true,
          }, undefined)
          return
        }
        // Nothing is committed yet, but the import may still be in flight, so
        // refresh the queue to show the real state and say the outcome is
        // unknown rather than claiming a failure that invites a retry.
        await invalidateAfterQueueMutation(queryClient)
        setUnknownOutcome(
          `We couldn't confirm whether "${seriesName}" was added — the connection dropped before ComicVine finished importing. Your queue has been refreshed; check it before adding again.`,
        )
        return
      }
      setError(err instanceof Error ? getApiErrorDetail(err) : 'Failed to add series from ComicVine')
    } finally {
      setIsAdding(false)
    }
  }, [alreadyReadCount, finishAdd, selectedSeries])

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' && step === 'search' && query.trim()) {
        if (debounceRef.current) clearTimeout(debounceRef.current)
        handleSearch(query)
      }
    },
    [step, query, handleSearch],
  )

  const maxAlreadyRead = selectedSeries?.issue_count ?? 0

  return (
    <Modal
      isOpen={isOpen}
      title="Add Series from ComicVine"
      onClose={onClose}
      size="large"
    >
      <div className="space-y-4">
        {(error || unknownOutcome) && (
          <div
            role="alert"
            className={
              unknownOutcome
                ? 'p-3 rounded-lg bg-amber-500/10 border border-amber-500/30 text-sm text-amber-200'
                : 'p-3 rounded-lg bg-rose-900/30 border border-rose-700/40 text-sm text-rose-300'
            }
          >
            {unknownOutcome ?? error}
          </div>
        )}

        {step === 'search' && (
          <>
            <p className="text-sm text-stone-400">
              Search for a ComicVine series to add to your queue.
            </p>
            <div className="relative">
              <input
                ref={inputRef}
                type="text"
                value={query}
                onChange={(e) => handleQueryChange(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Search series title (e.g., Batman, Saga, One Piece)"
                className="w-full min-h-11 rounded-xl px-4 pr-10 text-sm text-stone-100 bg-stone-800 border border-stone-600 focus:border-amber-500 focus:ring-1 focus:ring-amber-500 outline-none transition"
              />
              {isSearching && (
                <div className="absolute right-3 top-1/2 -translate-y-1/2">
                  <div className="w-4 h-4 border-2 border-amber-500/30 border-t-amber-500 rounded-full animate-spin" />
                </div>
              )}
            </div>
            {seriesResults.length > 0 && (
              <div className="space-y-2 max-h-96 overflow-y-auto overscroll-contain">
                {seriesResults.map((series) => (
                  <button
                    key={series.comicvine_volume_id}
                    type="button"
                    onClick={() => handleSelectSeries(series)}
                    aria-label={seriesAccessibleName(series)}
                    className="w-full text-left p-3 rounded-xl bg-stone-800/50 border border-stone-700/50 hover:border-amber-500/50 hover:bg-stone-800 transition group"
                  >
                    <div className="flex items-start gap-3">
                      {series.image_url && (
                        <ImageWithLoading
                          src={optimizedImageUrl(series.image_url, 240) ?? series.image_url}
                          srcSet={optimizedImageSrcSet(series.image_url, [96, 240]) ?? undefined}
                          sizes="40px"
                          alt=""
                          className="w-10 h-14 object-cover rounded-lg shrink-0"
                        />
                      )}
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-bold text-stone-100 group-hover:text-amber-300 transition truncate">
                          {series.name}
                        </p>
                        <p className="text-sm font-medium text-stone-300">
                          {seriesMetaText(series)}
                        </p>
                      </div>
                    </div>
                  </button>
                ))}
                {pagination.hasMore && pagination.nextOffset !== null && (
                  <button
                    type="button"
                    onClick={handleLoadMore}
                    disabled={isSearching}
                    className="w-full min-h-11 rounded-xl px-4 text-sm font-bold text-stone-200 bg-stone-800/50 border border-stone-700/50 hover:border-amber-500/50 hover:bg-stone-800 transition disabled:opacity-50"
                  >
                    {isSearching ? 'Loading...' : 'Load more'}
                  </button>
                )}
              </div>
            )}
            {!isSearching && !query.trim() && (
              <p className="text-sm text-stone-400 text-center py-4">
                Type a series name to search ComicVine
              </p>
            )}
            {!isSearching && query.trim() && seriesResults.length === 0 && !hasSearched && (
              <p className="text-sm text-stone-400 text-center py-4">
                Search ComicVine for the series you want to add
              </p>
            )}
            {!isSearching && query.trim() && seriesResults.length === 0 && hasSearched && !error && (
              <p className="text-sm text-stone-300 text-center py-4">
                No series found. Try a different search term.
              </p>
            )}
          </>
        )}

        {step === 'confirm' && selectedSeries && (
          <>
            <button
              type="button"
              onClick={() => {
                setStep('search')
                setSelectedSeries(null)
              }}
              className="text-sm text-amber-500 hover:text-amber-400 font-bold"
            >
              ← Back to search
            </button>
            <div className="p-4 rounded-xl bg-stone-800/50 border border-stone-700/50 space-y-3" data-testid="add-series-confirm-card">
              <p className="text-xs font-black uppercase tracking-wider text-stone-400">Selected series</p>
              <div className="flex items-start gap-3">
                {selectedSeries.image_url && (
                  <ImageWithLoading
                    src={optimizedImageUrl(selectedSeries.image_url, 240) ?? selectedSeries.image_url}
                    srcSet={optimizedImageSrcSet(selectedSeries.image_url, [96, 240]) ?? undefined}
                    sizes="64px"
                    alt=""
                    className="w-16 h-22 object-cover rounded-lg shrink-0"
                  />
                )}
                <div className="min-w-0">
                  <p className="text-sm font-bold text-stone-100">{selectedSeries.name}</p>
                  <p className="text-sm text-stone-300">
                    {seriesMetaText(selectedSeries)}
                  </p>
                </div>
              </div>
              <p className="text-xs text-stone-400">
                {existingSeries
                  ? `"${existingSeries.series_name ?? selectedSeries.name}" is already in your queue. Adding it again will not create a new series or duplicate issues — only missing issues are added to the existing series.`
                  : `This will create a new series in your queue with all ${selectedSeries.issue_count ?? '?'} issues from the ComicVine volume.`}
              </p>
            </div>
            {maxAlreadyRead > 0 && (
              <div className="space-y-2">
                <label
                  htmlFor="already-read-count"
                  className="text-[10px] font-black uppercase tracking-wider text-stone-500"
                >
                  Issues already read (optional)
                </label>
                <input
                  id="already-read-count"
                  type="number"
                  min="0"
                  max={maxAlreadyRead}
                  value={alreadyReadCount}
                  onChange={(e) => {
                    const value = Math.max(0, Math.min(Number.parseInt(e.target.value, 10) || 0, maxAlreadyRead))
                    setAlreadyReadCount(value)
                  }}
                  className="w-full rounded-xl px-3 py-2 text-sm form-control"
                />
                <p className="text-xs text-stone-400">
                  {alreadyReadCount > 0
                    ? `First ${alreadyReadCount} of ${maxAlreadyRead} issues will be marked as read`
                    : `Enter how many issues you've already read from the start of the series (max ${maxAlreadyRead})`}
                </p>
              </div>
            )}
            <button
              type="button"
              onClick={handleAdd}
              disabled={isAdding}
              className="w-full min-h-11 rounded-xl px-4 text-sm font-bold text-stone-900 bg-amber-500 hover:bg-amber-400 transition disabled:opacity-50"
            >
              {isAdding ? 'Adding...' : 'Add Series to ComicPile'}
            </button>
          </>
        )}
      </div>
    </Modal>
  )
}