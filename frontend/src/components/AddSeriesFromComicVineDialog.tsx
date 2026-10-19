import { useState, useCallback, useRef, useEffect } from 'react'
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
// Declared before the query-effect and error-helper imports so main's concurrent
// #3854 series-status imports stay in a separate hunk and merge cleanly (#3872).
import { LatestRequestGuard, type LoadPhase } from '../utils/latestRequest'
import { optimizedImageUrl, optimizedImageSrcSet } from '../services/imageDelivery'
import { useToast } from '../contexts/useToast'
import { queryClient } from '../query/queryClient'
import { invalidateAfterQueueMutation } from '../query/cacheEffects'
import { getApiErrorDetail, getApiErrorStatus } from '../utils/apiError'

interface AddSeriesFromComicVineDialogProps {
  isOpen: boolean
  onClose: () => void
  onAdded: (threadId: number) => void
}

type DialogStep = 'search' | 'select-series' | 'confirm'

/** The provider page currently listed under the search box. */
interface SeriesPagination {
  offset: number
  limit: number
  hasMore: boolean
  nextOffset: number | null
}

/** One provider search, identified well enough to repeat it exactly after a failure. */
interface SeriesSearch {
  query: string
  offset: number
  append: boolean
}

const SEARCH_PAGE_SIZE = 10
const SEARCH_DEBOUNCE_MS = 350

const EMPTY_PAGINATION: SeriesPagination = {
  offset: 0,
  limit: SEARCH_PAGE_SIZE,
  hasMore: false,
  nextOffset: null,
}

const SEARCH_ERROR_MESSAGE = 'Failed to search ComicVine. Please try again.'
const INVALID_RESPONSE_MESSAGE = 'Invalid response from ComicVine. Please try again.'

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
}): SeriesPagination {
  return {
    offset: response.offset || 0,
    limit: response.limit || SEARCH_PAGE_SIZE,
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
function importSuccessMessage({ seriesName, issuesAdopted, threadCreated }: ImportOutcome): string {
  if (issuesAdopted === null) {
    return `Added "${seriesName}" to ComicPile`
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
  const [pagination, setPagination] = useState<SeriesPagination>(EMPTY_PAGINATION)
  const [searchPhase, setSearchPhase] = useState<LoadPhase>('idle')
  const [isAdding, setIsAdding] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [unknownOutcome, setUnknownOutcome] = useState<string | null>(null)
  const [alreadyReadCount, setAlreadyReadCount] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  // Only the newest provider search may repaint the result list, so every keystroke,
  // every step change, and every dialog reset abandons the outstanding request first
  // instead of waiting for a network round trip to notice the reader moved on (#3448).
  const requestsRef = useRef(new LatestRequestGuard())
  const searchingRef = useRef(false)
  const lastSearchRef = useRef<SeriesSearch | null>(null)

  const searchLoading = searchPhase === 'loading'

  useEffect(() => {
    const requests = requestsRef.current
    return () => {
      if (debounceRef.current) {
        clearTimeout(debounceRef.current)
        debounceRef.current = null
      }
      // Unmounting abandons every outstanding request, so a late response cannot repaint a
      // component the reader has already dismissed (#3448).
      requests.abandon()
    }
  }, [])

  useEffect(() => {
    // Dismissing the dialog cancels the debounce too, so a dismissed surface stops asking
    // the provider for a term the reader already walked away from. A timer that survived
    // into the next session would search for that term against a reset, empty dialog, which
    // is the same late-result defect the reopen reset below already guards (#3872).
    if (debounceRef.current) {
      clearTimeout(debounceRef.current)
      debounceRef.current = null
    }
    if (isOpen) {
      // Reopening abandons whatever the previous session asked for, so its late response
      // cannot repopulate a dialog the reader has already reset.
      requestsRef.current.abandon()
      searchingRef.current = false
      lastSearchRef.current = null
      setStep('search')
      setQuery('')
      setSeriesResults([])
      setSelectedSeries(null)
      setPagination(EMPTY_PAGINATION)
      setSearchPhase('idle')
      setError(null)
      setUnknownOutcome(null)
      setAlreadyReadCount(0)
    }
  }, [isOpen])

  const handleSearch = useCallback(
    async (searchQuery: string, offset = 0, append = false) => {
      const trimmed = searchQuery.trim()
      if (!trimmed) {
        // An empty field is the idle state, not a failed search.
        requestsRef.current.abandon()
        searchingRef.current = false
        lastSearchRef.current = null
        setSeriesResults([])
        setPagination(EMPTY_PAGINATION)
        setSearchPhase('idle')
        setError(null)
        return
      }
      const requestId = requestsRef.current.begin()
      searchingRef.current = true
      lastSearchRef.current = { query: trimmed, offset, append }
      if (!append) {
        // A first page owns the whole list, so it replaces it outright. Enter and Retry both
        // reach this handler directly, and neither may leave the previous query's rows under
        // the new one's spinner (#3448).
        setSeriesResults([])
        setPagination(EMPTY_PAGINATION)
      }
      setSearchPhase('loading')
      setError(null)
      try {
        const response = await comicVineApi.searchSeries(trimmed, SEARCH_PAGE_SIZE, offset)
        if (!requestsRef.current.isCurrent(requestId)) return
        if (!response?.results) {
          setError(INVALID_RESPONSE_MESSAGE)
          // A first page that never arrived leaves nothing trustworthy to show; a failed
          // next page keeps the series the reader already has.
          setSeriesResults((previous) => (append ? previous : []))
          setSearchPhase('error')
          return
        }
        setSeriesResults((previous) =>
          append ? mergeSeriesResults(previous, response.results) : response.results,
        )
        setPagination(paginationFromResponse(response))
        setSearchPhase('ready')
      } catch {
        if (!requestsRef.current.isCurrent(requestId)) return
        setError(SEARCH_ERROR_MESSAGE)
        setSeriesResults((previous) => (append ? previous : []))
        setSearchPhase('error')
      } finally {
        if (requestsRef.current.isCurrent(requestId)) {
          searchingRef.current = false
        }
      }
    },
    [],
  )

  const handleQueryChange = useCallback(
    (value: string) => {
      setQuery(value)
      if (debounceRef.current) {
        clearTimeout(debounceRef.current)
        debounceRef.current = null
      }
      // Abandon the previous query the moment the box changes, before the debounce fires,
      // so a late response can never repaint results for a term the reader replaced or
      // deleted. Clearing the field counts as a change (#3448).
      requestsRef.current.abandon()
      searchingRef.current = false
      lastSearchRef.current = null
      setError(null)
      if (!value.trim()) {
        setSeriesResults([])
        setPagination(EMPTY_PAGINATION)
        setSearchPhase('idle')
        return
      }
      // The previous query's rows belong to the previous query: they must not sit under the
      // new one's spinner, so the list clears as soon as the new query starts.
      setSeriesResults([])
      setPagination(EMPTY_PAGINATION)
      setSearchPhase('loading')
      debounceRef.current = setTimeout(() => {
        debounceRef.current = null
        void handleSearch(value)
      }, SEARCH_DEBOUNCE_MS)
    },
    [handleSearch],
  )

  const handleRetrySearch = useCallback(() => {
    const failed = lastSearchRef.current
    if (!failed) return
    void handleSearch(failed.query, failed.offset, failed.append)
  }, [handleSearch])

  const handleLoadMore = useCallback(() => {
    if (!pagination.hasMore || pagination.nextOffset == null || searchingRef.current) return
    void handleSearch(query, pagination.nextOffset, true)
  }, [pagination, query, handleSearch])

  const handleSelectSeries = useCallback((series: ComicVineSeriesResult) => {
    setSelectedSeries(series)
    // Personal read progress belongs to one specific series. Selecting a
    // different run must not carry the previous volume's already-read count
    // into the new confirmation, where it would exceed the new issue count.
    setAlreadyReadCount(0)
    // The list the reader picked from is settled, so a paging failure stops here instead of
    // following them onto the confirmation, where no retry could act on it (#3448).
    requestsRef.current.abandon()
    searchingRef.current = false
    setError(null)
    setSearchPhase(seriesResults.length > 0 ? 'ready' : 'idle')
    setStep('confirm')
  }, [seriesResults.length])

  const handleBackToSearch = useCallback(() => {
    // Leaving the list abandons its outstanding request, so a late page cannot repaint
    // results the reader already walked away from (#3448).
    requestsRef.current.abandon()
    searchingRef.current = false
    // A failed import belongs to the step it happened on: the search screen has no action
    // that could retry it, so it must not follow the reader back (#3448).
    setError(null)
    setUnknownOutcome(null)
    setStep('search')
    setSelectedSeries(null)
  }, [])

  const finishAdd = useCallback(
    async (outcome: ImportOutcome) => {
      showToast(importSuccessMessage(outcome), 'success')
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
      })
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
          })
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
        if (debounceRef.current) {
          clearTimeout(debounceRef.current)
          debounceRef.current = null
        }
        void handleSearch(query)
      }
    },
    [step, query, handleSearch],
  )

  const maxAlreadyRead = selectedSeries?.issue_count ?? 0
  const showSearchRetry = error !== null && step === 'search' && searchPhase === 'error'
  const showResults = seriesResults.length > 0
  const showIdleHint = searchPhase === 'idle' && !query.trim() && !showResults

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
            {showSearchRetry && (
              <button
                type="button"
                onClick={handleRetrySearch}
                data-testid="add-series-comicvine-retry"
                className="mt-2 min-h-11 px-4 rounded-lg text-sm font-bold text-rose-100 bg-rose-800/60 border border-rose-600/50 hover:bg-rose-800 transition"
              >
                Retry
              </button>
            )}
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
              {searchLoading && (
                <div className="absolute right-3 top-1/2 -translate-y-1/2">
                  <div className="w-4 h-4 border-2 border-amber-500/30 border-t-amber-500 rounded-full animate-spin" />
                </div>
              )}
            </div>
            {showResults && (
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
                    disabled={searchLoading}
                    className="w-full min-h-11 rounded-xl px-4 text-sm font-bold text-stone-200 bg-stone-800/50 border border-stone-700/50 hover:border-amber-500/50 hover:bg-stone-800 transition disabled:opacity-50"
                  >
                    {searchLoading ? 'Loading...' : 'Load more'}
                  </button>
                )}
              </div>
            )}
            {showIdleHint && (
              <p className="text-sm text-stone-400 text-center py-4">
                Type a series name to search ComicVine
              </p>
            )}
            {searchPhase === 'ready' && !showResults && query.trim() && (
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
              onClick={handleBackToSearch}
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
                This will create a new series in your queue with all {selectedSeries.issue_count ?? '?'} issues from the ComicVine volume.
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