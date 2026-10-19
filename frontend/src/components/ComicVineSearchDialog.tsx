import { useCallback, useEffect, useRef, useState } from 'react'
import Modal from './Modal'
import { comicVineApi } from '../services/api-comicvine'
import type {
  ComicVineSeriesResult,
  ComicVineIssueCandidate,
  ComicVineResolveResponse,
  ComicVineResolvedIssue,
} from '../services/api-comicvine'
import ImageWithLoading from './ImageWithLoading'
import SiblingSeriesMappingOffer from './SiblingSeriesMappingOffer'
import { optimizedImageSrcSet, optimizedImageUrl } from '../services/imageDelivery'
import { LatestRequestGuard, type LoadPhase, type RequestTicket } from '../utils/latestRequest'

interface ComicVineSearchDialogProps {
  isOpen: boolean
  issueId: number | null
  threadTitle: string
  issueNumber: string | null
  mode?: 'confirm' | 'replace'
  onClose: () => void
  onConfirmed: (selected?: ComicVineIssueCandidate | null) => void
  onSiblingsMapped?: (confirmedIssueIds: number[]) => void
}

type DialogStep = 'search' | 'select-issue' | 'confirm' | 'siblings'

/**
 * Lifecycle of one async surface inside the dialog (#3448).
 *
 * The search step and the issue step each own exactly one of these phases at a time, so the
 * screen can be in exactly one of loading / results / empty / error. A phase is resolved only
 * by the request that is still current, which keeps out-of-order responses from flipping the
 * screen back to a state the reader already left. The type itself is shared with the Queue
 * "Add from ComicVine" dialog so both surfaces cannot drift apart.
 */

/** The provider volume a confirmed correction can license sibling scope for (#3159). */
interface SiblingScope {
  provider: string
  providerSeriesExternalId: string
  seriesLabel: string
}

interface SeriesPagination {
  offset: number
  limit: number
  hasMore: boolean
  nextOffset: number | null
}

const SEARCH_PAGE_SIZE = 10

const EMPTY_PAGINATION: SeriesPagination = {
  offset: 0,
  limit: SEARCH_PAGE_SIZE,
  hasMore: false,
  nextOffset: null,
}

const SEARCH_ERROR_MESSAGE = 'Failed to search ComicVine. Please try again.'
const ISSUES_ERROR_MESSAGE = 'Failed to load issues. Please try again.'

function seriesMetaParts(series: ComicVineSeriesResult): string[] {
  return [
    series.publisher,
    series.start_year ? `${series.start_year}` : null,
    series.issue_count ? `${series.issue_count} issues` : null,
  ].filter((part): part is string => part !== null)
}

function stripParenthesizedYears(title: string): string {
  return title.replace(/\((\d{4}(-\d{4})?)\)/g, '').trim()
}

function seriesMetaText(series: ComicVineSeriesResult): string {
  return seriesMetaParts(series).join(' · ')
}

function seriesAccessibleName(series: ComicVineSeriesResult): string {
  const parts = seriesMetaParts(series)
  return parts.length > 0 ? `${series.name} - ${parts.join(', ')}` : series.name
}

function isComicVineUrlLike(value: string): boolean {
  const trimmed = value.trim()
  return /^https?:\/\//i.test(trimmed) || trimmed.includes('://')
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
    offset: response.offset,
    limit: response.limit,
    hasMore: response.has_more,
    nextOffset: response.next_offset,
  }
}

export default function ComicVineSearchDialog({
  isOpen,
  issueId,
  threadTitle,
  issueNumber,
  mode = 'confirm',
  onClose,
  onConfirmed,
  onSiblingsMapped,
}: ComicVineSearchDialogProps) {
  const [step, setStep] = useState<DialogStep>('search')
  const [query, setQuery] = useState(threadTitle)
  const [seriesResults, setSeriesResults] = useState<ComicVineSeriesResult[]>([])
  const [selectedSeries, setSelectedSeries] = useState<ComicVineSeriesResult | null>(null)
  const [issueCandidates, setIssueCandidates] = useState<ComicVineIssueCandidate[]>([])
  const [selectedIssue, setSelectedIssue] = useState<ComicVineIssueCandidate | null>(null)
  const [directIssue, setDirectIssue] = useState<ComicVineResolvedIssue | null>(null)
  const [pagination, setPagination] = useState<SeriesPagination>(EMPTY_PAGINATION)
  const [searchPhase, setSearchPhase] = useState<LoadPhase>('idle')
  const [issuesPhase, setIssuesPhase] = useState<LoadPhase>('idle')
  const [isConfirming, setIsConfirming] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [siblingScope, setSiblingScope] = useState<SiblingScope | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const requestsRef = useRef(new LatestRequestGuard())
  const searchingRef = useRef(false)

  const searchLoading = searchPhase === 'loading'
  const issuesLoading = issuesPhase === 'loading'

  useEffect(() => {
    const requests = requestsRef.current
    return () => {
      if (debounceRef.current) {
        clearTimeout(debounceRef.current)
        debounceRef.current = null
      }
      // Closing the dialog abandons every outstanding request, so a late response cannot
      // repaint a component the reader has already dismissed (#3448).
      requests.abandon()
    }
  }, [])

  useEffect(() => {
    // Dismissing the dialog cancels the debounce too, so a dismissed surface stops asking
    // the provider for a term the reader already walked away from. The Queue "Add from
    // ComicVine" dialog cancels on the same transition, so the two cannot drift (#3872).
    if (debounceRef.current) {
      clearTimeout(debounceRef.current)
      debounceRef.current = null
    }
    if (isOpen && threadTitle) {
      setQuery(stripParenthesizedYears(threadTitle))
    }
    if (isOpen) {
      // Resetting the dialog context abandons whatever request is in flight, so its late
      // response cannot repaint a dialog that has already moved on to different state (#3448).
      requestsRef.current.abandon()
      searchingRef.current = false
      setStep('search')
      setSeriesResults([])
      setSelectedSeries(null)
      setIssueCandidates([])
      setSelectedIssue(null)
      setDirectIssue(null)
      setPagination(EMPTY_PAGINATION)
      setSearchPhase('idle')
      setIssuesPhase('idle')
      setError(null)
      setSiblingScope(null)
    }
  }, [isOpen, threadTitle])

  const hasAutoSearchedRef = useRef(false)

  const handlePlainSearch = useCallback(
    async (searchQuery: string, offset = 0, append = false) => {
      const requestId = requestsRef.current.begin()
      searchingRef.current = true
      setSearchPhase('loading')
      setError(null)
      if (!append) {
        setSeriesResults([])
        setPagination(EMPTY_PAGINATION)
      }
      try {
        const response = await comicVineApi.searchSeries(searchQuery, SEARCH_PAGE_SIZE, offset)
        if (!requestsRef.current.isCurrent(requestId)) return
        setSeriesResults((previous) =>
          append ? mergeSeriesResults(previous, response.results) : response.results,
        )
        setPagination(paginationFromResponse(response))
        setSearchPhase('ready')
      } catch {
        if (!requestsRef.current.isCurrent(requestId)) return
        setError(SEARCH_ERROR_MESSAGE)
        setSeriesResults([])
        setPagination(EMPTY_PAGINATION)
        setSearchPhase('error')
      } finally {
        if (requestsRef.current.isCurrent(requestId)) {
          searchingRef.current = false
        }
      }
    },
    [],
  )

  const handleDirectResolution = useCallback(
    (resolved: ComicVineResolveResponse) => {
      if (resolved.validation_error) {
        setSeriesResults([])
        setPagination(EMPTY_PAGINATION)
        setError(resolved.validation_error)
        setSearchPhase('error')
        return
      }
      if (resolved.kind === 'issue') {
        if (resolved.issue) {
          setDirectIssue(resolved.issue)
          setSelectedIssue(null)
          setSelectedSeries(null)
          setIssueCandidates([])
          setIssuesPhase('idle')
          setSearchPhase('ready')
          setStep('confirm')
          return
        } else {
          setError('Failed to resolve ComicVine issue. Please try again.')
          setSearchPhase('error')
          return
        }
      }
      if (resolved.kind === 'volume') {
        if (resolved.volume) {
          setDirectIssue(null)
          setSelectedIssue(null)
          setSelectedSeries(resolved.volume)
          setIssueCandidates(resolved.issues)
          setIssuesPhase('ready')
          // A pasted volume URL is not a text search, so the search step has no
          // results to show when the reader navigates back to it.
          setSearchPhase('idle')
          setStep('select-issue')
          if (issueNumber) {
            const normalizedIssueNumber = issueNumber.trim()
            const match = resolved.issues.find(
              (issue) => issue.issue_number?.trim() === normalizedIssueNumber,
            )
            if (match) {
              setSelectedIssue(match)
              setStep('confirm')
            }
          }
          return
        } else {
          setError('Failed to resolve ComicVine volume. Please try again.')
          setSearchPhase('error')
          return
        }
      }
      if (resolved.kind === 'search') {
        const remainingQuery = resolved.input.trim()
        if (remainingQuery) {
          void handlePlainSearch(remainingQuery)
        }
      }
    },
    [handlePlainSearch, issueNumber],
  )


  const handleSearch = useCallback(
    async (searchQuery: string, offset = 0, append = false) => {
      // The guard issues no ticket until begin(), so the initial 0 is never current and a
      // response can only be applied once this search owns the surface.
      let requestId: RequestTicket = 0
      try {
        if (!searchQuery.trim()) {
          requestsRef.current.abandon()
          setSeriesResults([])
          setPagination(EMPTY_PAGINATION)
          setSearchPhase('idle')
          setError(null)
          searchingRef.current = false
          return
        }
        requestId = requestsRef.current.begin()
        searchingRef.current = true
        if (!append) {
          // A first page owns the whole list, so it replaces it outright. Enter and Retry both
          // reach this handler directly, and neither may leave the previous query's rows under
          // the new one's spinner (#3448).
          setSeriesResults([])
          setPagination(EMPTY_PAGINATION)
        }
        // Enter and Retry reach here directly (bypassing handleQueryChange's debounce), so we
        // must set the loading phase here so the spinner shows while ComicVine answers.
        setSearchPhase('loading')
        setError(null)
        const trimmed = searchQuery.trim()
        if (isComicVineUrlLike(trimmed)) {
          const resolved = await comicVineApi.resolveIdentity(trimmed)
          if (!requestsRef.current.isCurrent(requestId)) {
            searchingRef.current = false
            return
          }
          handleDirectResolution(resolved)
          searchingRef.current = false
          return
        }
        const response = await comicVineApi.searchSeries(trimmed, SEARCH_PAGE_SIZE, offset)
        if (!requestsRef.current.isCurrent(requestId)) {
          searchingRef.current = false
          return
        }
        if (!append) {
          setSeriesResults([])
          setPagination(EMPTY_PAGINATION)
        }
        setSeriesResults((previous) =>
          append ? mergeSeriesResults(previous, response.results) : response.results,
        )
        setPagination(paginationFromResponse(response))
        setSearchPhase('ready')
      } catch {
        if (!requestsRef.current.isCurrent(requestId)) {
          searchingRef.current = false
          return
        }
        setError(SEARCH_ERROR_MESSAGE)
        setSeriesResults([])
        setPagination(EMPTY_PAGINATION)
        setSearchPhase('error')
      } finally {
        if (requestsRef.current.isCurrent(requestId)) {
          searchingRef.current = false
        }
      }
    },
    [handleDirectResolution],
  )

  useEffect(() => {
    if (isOpen && threadTitle.trim() && !hasAutoSearchedRef.current) {
      hasAutoSearchedRef.current = true
      void handleSearch(stripParenthesizedYears(threadTitle))
    }
    if (!isOpen) {
      hasAutoSearchedRef.current = false
    }
  }, [isOpen, threadTitle, handleSearch])

  const handleQueryChange = useCallback(
    (value: string) => {
      setQuery(value)
      if (debounceRef.current) clearTimeout(debounceRef.current)
      // Every query change abandons the previous query immediately, before the debounce
      // fires, so a late response can never repaint results the reader has already left
      // behind. Clearing the field counts as a change: an in-flight search for the abandoned
      // term must not repopulate results under an empty query (#3448).
      requestsRef.current.abandon()
      searchingRef.current = false
      if (!value.trim()) {
        setSeriesResults([])
        setPagination(EMPTY_PAGINATION)
        setSearchPhase('idle')
        setError(null)
        return
      }
      setSeriesResults([])
      setPagination(EMPTY_PAGINATION)
      setError(null)
      setSearchPhase('loading')
      debounceRef.current = setTimeout(() => {
        void handleSearch(value)
      }, 350)
    },
    [handleSearch],
  )

  const handleLoadMore = useCallback(() => {
    if (!pagination.hasMore || pagination.nextOffset == null || searchingRef.current) return
    void handleSearch(query, pagination.nextOffset, true)
  }, [pagination, query, handleSearch])

  const handleSelectSeries = useCallback(
    async (series: ComicVineSeriesResult) => {
      setSelectedSeries(series)
      setStep('select-issue')
      setIssuesPhase('loading')
      setIssueCandidates([])
      setError(null)
      // Selecting a series supersedes any in-flight search, so keep the search step
      // from being stuck on its loading phase when the reader navigates back.
      searchingRef.current = false
      setSearchPhase((phase) => (phase === 'loading' ? 'idle' : phase))
      const requestId = requestsRef.current.begin()
      try {
        const response = await comicVineApi.getSeriesIssues(series.comicvine_volume_id, series.name)
        if (!requestsRef.current.isCurrent(requestId)) return
        setIssueCandidates(response.issues)
        setIssuesPhase('ready')
        if (issueNumber) {
          const normalizedIssueNumber = issueNumber.trim()
          const match = response.issues.find(
            (issue) => issue.issue_number?.trim() === normalizedIssueNumber,
          )
          if (match) {
            setSelectedIssue(match)
            setStep('confirm')
          }
        }
      } catch {
        if (!requestsRef.current.isCurrent(requestId)) return
        setError(ISSUES_ERROR_MESSAGE)
        setIssueCandidates([])
        setIssuesPhase('error')
      }
    },
    [issueNumber],
  )

  const handleSelectIssue = useCallback((issue: ComicVineIssueCandidate) => {
    setDirectIssue(null)
    setSelectedIssue(issue)
    setStep('confirm')
  }, [])

  const handleConfirm = useCallback(async () => {
    const targetIssue = directIssue ?? selectedIssue
    if (!issueId || !targetIssue) return
    setIsConfirming(true)
    setError(null)
    try {
      if (mode === 'replace') {
        await comicVineApi.replaceIdentity(issueId, targetIssue.comicvine_issue_id)
      } else {
        await comicVineApi.confirmIdentity(issueId, targetIssue.comicvine_issue_id)
      }
      onConfirmed(targetIssue)
      // Issue #3159: confirming one issue's volume licenses sibling scope, so the
      // remaining numbered siblings become offerable. Keep the dialog open for that
      // offer instead of closing the moment the single-issue correction lands.
      const volumeId = directIssue?.volume_id ?? selectedSeries?.comicvine_volume_id ?? null
      if (volumeId != null) {
        setSiblingScope({
          provider: 'comicvine',
          providerSeriesExternalId: String(volumeId),
          seriesLabel: directIssue?.series_name ?? selectedSeries?.name ?? threadTitle,
        })
        setStep('siblings')
      } else {
        onClose()
      }
    } catch {
      setError('Failed to confirm identity. Please try again.')
    } finally {
      setIsConfirming(false)
    }
  }, [issueId, directIssue, selectedIssue, mode, onConfirmed, onClose, selectedSeries, threadTitle])

  const handleRetry = useCallback(() => {
    if (step === 'select-issue' && selectedSeries) {
      void handleSelectSeries(selectedSeries)
      return
    }
    if (query.trim()) {
      void handleSearch(query)
    }
  }, [step, selectedSeries, query, handleSelectSeries, handleSearch])

  const handleDismissSiblings = useCallback(() => {
    setSiblingScope(null)
    onClose()
  }, [onClose])

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' && step === 'search' && query.trim()) {
        if (debounceRef.current) clearTimeout(debounceRef.current)
        void handleSearch(query)
      }
    },
    [step, query, handleSearch],
  )

  const confirmSeriesName = directIssue?.series_name ?? selectedSeries?.name ?? threadTitle
  const confirmIssue = directIssue ?? selectedIssue

  const showRetry =
    error !== null
    && ((step === 'search' && searchPhase === 'error')
      || (step === 'select-issue' && issuesPhase === 'error'))

  const dialogTitle =
    step === 'search'
      ? 'Find ComicVine Match'
      : step === 'select-issue'
        ? 'Select Issue'
        : step === 'siblings'
          ? 'Map Sibling Issues'
          : 'Confirm Match'

  return (
    <Modal
      isOpen={isOpen}
      title={dialogTitle}
      onClose={onClose}
      size="large"
    >
      <div className="space-y-4">
        {error && (
          <div className="p-3 rounded-lg bg-rose-900/30 border border-rose-700/40 text-sm text-rose-300 space-y-2" role="alert">
            <p>{error}</p>
            {showRetry && (
              <button
                type="button"
                onClick={handleRetry}
                data-testid="comicvine-retry"
                className="min-h-11 px-4 rounded-lg text-sm font-bold text-rose-100 bg-rose-800/60 border border-rose-600/50 hover:bg-rose-800 transition"
              >
                Retry
              </button>
            )}
          </div>
        )}

        {step === 'search' && (
          <>
            <p className="text-sm text-stone-400">
              Search for the correct ComicVine series for{' '}
              <span className="font-bold text-stone-200">
                {threadTitle}
                {issueNumber ? ` #${issueNumber}` : ''}
              </span>
            </p>
            <div className="relative">
              <input
                ref={inputRef}
                type="text"
                value={query}
                onChange={(e) => handleQueryChange(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Search series title or paste a ComicVine URL"
                className="w-full min-h-11 rounded-xl px-4 pr-10 text-sm text-stone-100 bg-stone-800 border border-stone-600 focus:border-amber-500 focus:ring-1 focus:ring-amber-500 outline-none transition"
              />
              {searchLoading && (
                <div className="absolute right-3 top-1/2 -translate-y-1/2">
                  <div className="w-4 h-4 border-2 border-amber-500/30 border-t-amber-500 rounded-full animate-spin" />
                </div>
              )}
            </div>
            <p className="text-xs text-stone-500" data-testid="comicvine-resolve-hint">
              You can also paste a ComicVine issue or volume URL (comicvine.gamespot.com) to skip searching.
            </p>
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
                    disabled={searchLoading}
                    data-testid="comicvine-load-more"
                    className="w-full min-h-11 rounded-xl px-4 text-sm font-bold text-stone-200 bg-stone-800/50 border border-stone-700/50 hover:border-amber-500/50 hover:bg-stone-800 transition disabled:opacity-50"
                  >
                    {searchLoading ? 'Loading...' : 'Load more'}
                  </button>
                )}
              </div>
            )}
            {!query.trim() && (
              <p className="text-sm text-stone-400 text-center py-4">
                Type a series name to search ComicVine
              </p>
            )}
            {query.trim() && seriesResults.length === 0 && searchPhase === 'idle' && (
              <p className="text-sm text-stone-400 text-center py-4">
                Search ComicVine for the correct series
              </p>
            )}
            {query.trim() && seriesResults.length === 0 && searchPhase === 'ready' && (
              <p className="text-sm text-stone-300 text-center py-4">
                No series found. Try a different search term.
              </p>
            )}
          </>
        )}

        {step === 'select-issue' && selectedSeries && (
          <>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => {
                  // Leaving the issue step abandons its outstanding request, so a late success
                  // cannot pull the reader onto the confirm step and a late failure cannot
                  // follow them back onto the search screen (#3448).
                  requestsRef.current.abandon()
                  searchingRef.current = false
                  setStep('search')
                  setSelectedSeries(null)
                  setIssueCandidates([])
                  setIssuesPhase('idle')
                  setError(null)
                  setSearchPhase(seriesResults.length > 0 ? 'ready' : 'idle')
                }}
                className="text-sm text-amber-500 hover:text-amber-400 font-bold"
              >
                ← Back to search
              </button>
              <span className="text-xs text-stone-500">·</span>
              <span className="text-sm text-stone-300 truncate">
                {selectedSeries.name}
                {seriesMetaText(selectedSeries) && ` (${seriesMetaText(selectedSeries)})`}
              </span>
            </div>
            {issueNumber && (
              <p
                className="text-sm text-stone-300 bg-stone-800/40 border border-stone-700/40 rounded-lg px-3 py-2"
                data-testid="rematch-issue-context"
              >
                Looking for <span className="font-bold text-stone-100">#{issueNumber}</span> — select the
                matching issue below to confirm.
              </p>
            )}
            {issuesLoading ? (
              <div className="flex justify-center py-8">
                <div className="w-5 h-5 border-2 border-amber-500/30 border-t-amber-500 rounded-full animate-spin" />
              </div>
            ) : issueCandidates.length > 0 ? (
              <div className="space-y-2 max-h-96 overflow-y-auto overscroll-contain">
                {issueCandidates.map((issue) => (
                  <button
                    key={issue.comicvine_issue_id}
                    type="button"
                    onClick={() => handleSelectIssue(issue)}
                    className="w-full text-left p-3 rounded-xl bg-stone-800/50 border border-stone-700/50 hover:border-amber-500/50 hover:bg-stone-800 transition group"
                  >
                    <div className="flex items-center gap-3">
                      {issue.image_url && (
                        <ImageWithLoading
                          src={optimizedImageUrl(issue.image_url, 240) ?? issue.image_url}
                          srcSet={optimizedImageSrcSet(issue.image_url, [96, 240]) ?? undefined}
                          sizes="32px"
                          alt=""
                          className="w-8 h-11 object-cover rounded shrink-0"
                        />
                      )}
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-bold text-stone-100 group-hover:text-amber-300 transition">
                          {issue.issue_number ? `#${issue.issue_number}` : 'Unknown'}
                          {issue.name && <span className="font-normal text-stone-300 ml-2">{issue.name}</span>}
                        </p>
                        {issue.cover_date && (
                          <p className="text-xs text-stone-400">{issue.cover_date}</p>
                        )}
                      </div>
                    </div>
                  </button>
                ))}
              </div>
            ) : issuesPhase === 'ready' ? (
              <p className="text-sm text-stone-400 text-center py-4">
                {issueNumber
                  ? `No match for #${issueNumber} in this series.`
                  : 'No issues found in this series.'}
              </p>
            ) : null}
          </>
        )}

        {step === 'confirm' && confirmIssue && (
          <>
            <button
              type="button"
              onClick={() => {
                if (directIssue) {
                  setDirectIssue(null)
                  setStep('search')
                } else {
                  setStep('select-issue')
                  setSelectedIssue(null)
                }
              }}
              className="text-sm text-amber-500 hover:text-amber-400 font-bold"
            >
              {directIssue ? '← Back to search' : '← Back to issues'}
            </button>
            <div className="p-4 rounded-xl bg-stone-800/50 border border-stone-700/50 space-y-3" data-testid="comicvine-confirm-card">
              <p className="text-xs font-black uppercase tracking-wider text-stone-400">Selected match</p>
              <div className="flex items-start gap-3">
                {confirmIssue.image_url && (
                  <ImageWithLoading
                    src={optimizedImageUrl(confirmIssue.image_url, 240) ?? confirmIssue.image_url}
                    srcSet={optimizedImageSrcSet(confirmIssue.image_url, [96, 240]) ?? undefined}
                    sizes="64px"
                    alt=""
                    className="w-16 h-22 object-cover rounded-lg shrink-0"
                  />
                )}
                <div className="min-w-0">
                  <p className="text-sm font-bold text-stone-100">{confirmSeriesName}</p>
                  <p className="text-sm text-stone-300">
                    {confirmIssue.issue_number ? `#${confirmIssue.issue_number}` : ''}
                    {confirmIssue.name && ` — ${confirmIssue.name}`}
                  </p>
                  {confirmIssue.cover_date && (
                    <p className="text-xs text-stone-400 mt-1">{confirmIssue.cover_date}</p>
                  )}
                </div>
              </div>
              <p className="text-xs text-stone-400">
                {directIssue
                  ? `You pasted the ComicVine URL for this issue. Confirming will map ${threadTitle} ${issueNumber ? `#${issueNumber}` : ''} to it.`
                  : `This will confirm ${threadTitle} ${issueNumber ? `#${issueNumber}` : ''} maps to this ComicVine issue.`}
              </p>
            </div>
            <button
              type="button"
              onClick={handleConfirm}
              disabled={isConfirming}
              className="w-full min-h-11 rounded-xl px-4 text-sm font-bold text-stone-900 bg-amber-500 hover:bg-amber-400 transition disabled:opacity-50"
            >
              {isConfirming ? 'Confirming...' : 'Confirm Identity'}
            </button>
          </>
        )}

        {step === 'siblings' && issueId && siblingScope && (
          <SiblingSeriesMappingOffer
            originIssueId={issueId}
            provider={siblingScope.provider}
            providerSeriesExternalId={siblingScope.providerSeriesExternalId}
            seriesLabel={siblingScope.seriesLabel}
            onMapped={(confirmedIssueIds) => onSiblingsMapped?.(confirmedIssueIds)}
            onDismiss={handleDismissSiblings}
          />
        )}
      </div>
    </Modal>
  )
}
