import { usePotentialDuplicates } from '../hooks/usePotentialDuplicates'
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
import type { PotentialDuplicateMatch } from '../types'
import ImageWithLoading from './ImageWithLoading'
// Declared before the query-effect and error-helper imports so main's concurrent
// #3854 series-status imports stay in a separate hunk and merge cleanly (#3872).
import { LatestRequestGuard, type LoadPhase } from '../utils/latestRequest'
import { useToast } from '../contexts/useToast'
import { queryClient } from '../query/queryClient'
import { invalidateAfterQueueMutation, invalidateComicVineImportStatus } from '../query/cacheEffects'
import { getApiErrorDetail, getApiErrorStatus } from '../utils/apiError'
import { formatIssueCount } from '../utils/formatIssueCount'
import { queryKeys } from '../query/queryKeys'

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
    series.issue_count ? formatIssueCount(series.issue_count) : null,
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
 *
 * `result` is the import response, which only a completed import has. A
 * zero-adopted retry against an existing series is only genuinely "already up
 * to date" when every issue was reused; the per-issue outcomes say whether
 * conflicts or failures left issues still missing, and claiming completeness
 * over those would send the user away from work that is not done (#3854).
 */
function importSuccessMessage({ seriesName, issuesAdopted, threadCreated }: ImportOutcome, result?: ComicVineImportSeriesResult): string {
  if (issuesAdopted === null) {
    return `Added "${seriesName}" to ComicPile`
  }
  if (!threadCreated && issuesAdopted === 0) {
    // Zero adopted is not proof of completeness: a reused issue reports the
    // same count whether it was cleanly skipped, conflicted, or failed.
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
    ? `Added "${seriesName}" to ComicPile (${formatIssueCount(issuesAdopted)})`
    : `Added ${issuesAdopted} more ${issuesAdopted === 1 ? 'issue' : 'issues'} to "${seriesName}"`
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
  // Keep the draft as text so a fractional or negative entry can be reported
  // instead of silently truncated/clamped (#3451). The API only accepts whole
  // counts from 0 through the selected volume's issue count.
  const [alreadyReadInput, setAlreadyReadInput] = useState('0')
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
      setAlreadyReadInput('0')
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
    // One read is enough: this only refines copy, and the import it describes
    // stays idempotent server-side either way, so retrying a failing endpoint
    // would add load without changing what the server does.
    retry: false,
    // The status endpoint answers for every volume; only an `imported` volume
    // means the confirm copy should say "already in your queue".
    select: (status) => (status?.imported ? status : null),
  })

  const duplicateQuery = usePotentialDuplicates({ title: selectedSeries?.name ?? '', format: 'Comic',
    comicvine_volume_id: selectedSeries?.comicvine_volume_id }, isOpen && step === 'confirm')
  const potentialDuplicates = duplicateQuery.matches
  const isCheckingDuplicates = duplicateQuery.isChecking

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

  const handleRetrySearch = () => {
    const failed = lastSearchRef.current
    if (!failed) return
    void handleSearch(failed.query, failed.offset, failed.append)
  }

  const handleLoadMore = useCallback(() => {
    if (!pagination.hasMore || pagination.nextOffset == null || searchingRef.current) return
    void handleSearch(query, pagination.nextOffset, true)
  }, [pagination, query, handleSearch])

  const handleSelectSeries = useCallback((series: ComicVineSeriesResult) => {
    setSelectedSeries(series)
    // Personal read progress belongs to one specific series. Selecting a
    // different run must not carry the previous volume's already-read count
    // into the new confirmation, where it would exceed the new issue count.
    setAlreadyReadInput('0')
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
    // stable dependencies: requestsRef (ref), setError/setUnknownOutcome/setStep/setSelectedSeries (useState)
  }, [])

  const finishAdd = useCallback(
    async (volumeId: number, outcome: ImportOutcome, result?: ComicVineImportSeriesResult) => {
      showToast(importSuccessMessage(outcome, result), 'success')
      await invalidateAfterQueueMutation(queryClient)
      // This import just changed what the server answers for this volume, so the
      // confirm step's cached "not imported" reply must not outlive it. Without
      // this, re-selecting the series in the same session promised a brand-new
      // series for one the user had just added (#3854).
      await invalidateComicVineImportStatus(queryClient, volumeId)
      onAdded(outcome.threadId)
      onClose()
    },
    [onAdded, onClose, showToast],
  )

  const maxAlreadyRead = selectedSeries?.issue_count ?? 0
  const trimmedAlreadyRead = alreadyReadInput.trim()
  // An untouched/cleared field means "no prior reading", not an invalid entry.
  const alreadyReadCount = trimmedAlreadyRead === '' ? 0 : Number(trimmedAlreadyRead)
  const alreadyReadIsInteger = /^\d+$/.test(trimmedAlreadyRead || '0')
  const alreadyReadIsValid =
    alreadyReadIsInteger && alreadyReadCount >= 0 && alreadyReadCount <= maxAlreadyRead

  const handleAdd = useCallback(async () => {
    if (!selectedSeries || !alreadyReadIsValid) return
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
      await finishAdd(
        volumeId,
        {
          threadId: result.thread_id,
          seriesName: result.series_name,
          issuesAdopted: result.issues_adopted,
          threadCreated: result.thread_created,
        },
        result,
      )
    } catch (err: unknown) {
      // An import that outlives the client budget keeps running server-side and
      // commits after the client gives up, so a request the server never
      // answered proves nothing (#3445). Ask the server what actually happened
      // before reporting an error the user would answer with a duplicate retry.
      if (hasUnknownOutcome(err)) {
        const committed = await readCommittedImport(volumeId)
        if (committed?.thread_id != null) {
          await finishAdd(
            volumeId,
            {
              threadId: committed.thread_id,
              seriesName: committed.series_name ?? seriesName,
              issuesAdopted: committed.issue_count,
              threadCreated: true,
            },
            undefined,
          )
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
  }, [alreadyReadCount, alreadyReadIsValid, finishAdd, selectedSeries])

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
                className="mt-2 min-h-11 px-4 rounded-lg text-sm font-bold text-white bg-[var(--theme-primary-action)] border border-[var(--theme-primary-action)] hover:bg-[var(--theme-primary-action-hover)] hover:border-[var(--theme-primary-action-hover)] transition"
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
                          src={series.image_url}
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
                    src={selectedSeries.image_url}
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
                  : `This will create a new series in your queue with ${selectedSeries.issue_count == null ? 'all issues' : formatIssueCount(selectedSeries.issue_count)} from the ComicVine volume.`}
              </p>
            </div>

            {(potentialDuplicates.length > 0 || isCheckingDuplicates) && (
              <div
                className="space-y-2 p-3 rounded-xl bg-[var(--theme-bg-panel)] border border-[var(--theme-warning)]"
                role="alert"
                aria-live="polite"
              >
                {isCheckingDuplicates ? (
                  <div className="flex items-center gap-2 text-sm text-[var(--theme-warning)]">
                    <div className="w-4 h-4 border-2 border-[var(--theme-warning)] border-t-[var(--theme-warning)] rounded-full animate-spin motion-reduce:animate-none" />
                    Checking for potential duplicates...
                  </div>
                ) : (
                  <>
                    <p className="text-sm font-bold text-[var(--theme-warning)]">
                      {potentialDuplicates.some((m) => m.match_type === 'strong')
                        ? '⚠ Same ComicVine volume already in your library'
                        : '⚠ Similar series found in your library'}
                    </p>
                    <p className="text-xs text-[var(--theme-text-primary)]">
                      {potentialDuplicates.some((m) => m.match_type === 'strong')
                        ? 'This ComicVine volume is already linked to an existing series. Adding it again will not create a new series or duplicate issues.'
                        : 'A series with a similar title and format already exists. You can still add this series if it\'s a different volume or edition.'}
                    </p>
                    <div className="space-y-1.5">
                      {potentialDuplicates.map((match) => (
                        <div
                          key={match.thread_id}
                          className="p-2 rounded-lg bg-[var(--theme-bg-panel)] border border-[var(--theme-border)]"
                        >
                          <div className="flex items-start gap-2">
                            <span
                              className={`text-xs px-2 py-0.5 rounded-full ${
                                match.match_type === 'strong'
                                  ? 'bg-[var(--theme-bg-panel)] text-[var(--theme-warning)]'
                                  : 'bg-[var(--theme-bg-panel)] text-[var(--theme-text-primary)]'
                              }`}
                            >
                              {match.match_type === 'strong' ? 'Same ComicVine Volume' : 'Similar Title/Format'}
                            </span>
                          </div>
                          <p className="text-sm font-medium text-[var(--theme-text-primary)] mt-1">{match.title}</p>
                          <div className="flex flex-wrap gap-2 text-xs text-[var(--theme-text-muted)] mt-1">
                            <span>{match.format}</span>
                            <span>•</span>
                            <span>
                              {match.total_issues
                                ? `${match.total_issues} issues`
                                : `${match.issues_remaining} remaining`}
                            </span>
                            {match.start_year != null && (
                              <>
                                <span>•</span>
                                <span>Started {match.start_year}</span>
                              </>
                            )}
                            <span>•</span>
                            <span>{match.status}</span>
                          </div>
                          <p className="text-xs text-[var(--theme-text-dim)] mt-1">
                            Thread ID: {match.thread_id}
                            {match.match_type === 'strong' && match.comicvine_volume_id && (
                              <> • ComicVine Volume: {match.comicvine_volume_id}</>
                            )}
                          </p>
                        </div>
                      ))}
                    </div>
                  </>
                )}
              </div>
            )}

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
                  step="1"
                  inputMode="numeric"
                  value={alreadyReadInput}
                  onChange={(e) => setAlreadyReadInput(e.target.value)}
                  aria-invalid={!alreadyReadIsValid}
                  aria-describedby={
                    alreadyReadIsValid ? 'already-read-hint' : 'already-read-error'
                  }
                  className="w-full rounded-xl px-3 py-2 text-sm form-control"
                />
                {alreadyReadIsValid ? (
                  <p id="already-read-hint" className="text-xs text-stone-400">
                    {alreadyReadCount > 0
                      ? `First ${alreadyReadCount} of ${formatIssueCount(maxAlreadyRead)} will be marked as read`
                      : `Enter how many issues you've already read from the start of the series (max ${formatIssueCount(maxAlreadyRead)})`}
                  </p>
                ) : (
                  <p
                    id="already-read-error"
                    role="alert"
                    className="text-xs text-[var(--theme-danger)]"
                  >
                    Enter a whole number from 0 to {maxAlreadyRead}.
                  </p>
                )}
              </div>
            )}
            <button
              type="button"
              onClick={handleAdd}
              disabled={isAdding || !alreadyReadIsValid}
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