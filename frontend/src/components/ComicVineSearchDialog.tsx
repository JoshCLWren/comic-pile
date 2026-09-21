import { useState, useCallback, useRef, useEffect } from 'react'
import Modal from './Modal'
import {
  comicVineApi,
  type ComicVineSeriesResult,
  type ComicVineIssueCandidate,
  type ComicVineResolveResponse,
  type ComicVineResolvedIssue,
} from '../services/api'
import ImageWithLoading from './ImageWithLoading'
import { optimizedImageSrcSet, optimizedImageUrl } from '../services/imageDelivery'

interface ComicVineSearchDialogProps {
  isOpen: boolean
  issueId: number | null
  threadTitle: string
  issueNumber: string | null
  mode?: 'confirm' | 'replace'
  onClose: () => void
  onConfirmed: (selected?: ComicVineIssueCandidate | null) => void
}

type DialogStep = 'search' | 'select-issue' | 'confirm'

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
  return parts.length > 0 ? `${series.name} — ${parts.join(', ')}` : series.name
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
}: ComicVineSearchDialogProps) {
  const [step, setStep] = useState<DialogStep>('search')
  const [query, setQuery] = useState(threadTitle)
  const [seriesResults, setSeriesResults] = useState<ComicVineSeriesResult[]>([])
  const [selectedSeries, setSelectedSeries] = useState<ComicVineSeriesResult | null>(null)
  const [issueCandidates, setIssueCandidates] = useState<ComicVineIssueCandidate[]>([])
  const [selectedIssue, setSelectedIssue] = useState<ComicVineIssueCandidate | null>(null)
  const [directIssue, setDirectIssue] = useState<ComicVineResolvedIssue | null>(null)
  const [pagination, setPagination] = useState<SeriesPagination>(EMPTY_PAGINATION)
  const [isSearching, setIsSearching] = useState(false)
  const [isConfirming, setIsConfirming] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [hasSearched, setHasSearched] = useState(false)
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
    if (isOpen && threadTitle) {
      setQuery(threadTitle)
    }
    if (isOpen) {
      setStep('search')
      setSeriesResults([])
      setSelectedSeries(null)
      setIssueCandidates([])
      setSelectedIssue(null)
      setDirectIssue(null)
      setPagination(EMPTY_PAGINATION)
      setError(null)
      setHasSearched(false)
    }
  }, [isOpen, threadTitle])

  const hasAutoSearchedRef = useRef(false)

  const handleDirectResolution = useCallback(
    (resolved: ComicVineResolveResponse) => {
      if (resolved.validation_error) {
        setSeriesResults([])
        setPagination(EMPTY_PAGINATION)
        setError(resolved.validation_error)
        return
      }
      if (resolved.kind === 'issue' && resolved.issue) {
        setDirectIssue(resolved.issue)
        setSelectedIssue(null)
        setSelectedSeries(null)
        setIssueCandidates([])
        setStep('confirm')
        return
      }
      if (resolved.kind === 'volume' && resolved.volume) {
        setDirectIssue(null)
        setSelectedIssue(null)
        setSelectedSeries(resolved.volume)
        setIssueCandidates(resolved.issues)
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
      }
      if (resolved.kind === 'search') {
        const remainingQuery = resolved.input.trim()
        if (remainingQuery) {
          handlePlainSearch(remainingQuery)
        }
      }
    },
    [handlePlainSearch, issueNumber],
  )

  const handlePlainSearch = useCallback(
    async (searchQuery: string, offset = 0, append = false) => {
      const requestId = ++asyncRef.current
      searchingRef.current = true
      setIsSearching(true)
      try {
        const response = await comicVineApi.searchSeries(searchQuery, SEARCH_PAGE_SIZE, offset)
        if (requestId !== asyncRef.current) return
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
        const trimmed = searchQuery.trim()
        if (isComicVineUrlLike(trimmed)) {
          const resolved = await comicVineApi.resolveIdentity(trimmed)
          if (requestId !== asyncRef.current) return
          handleDirectResolution(resolved)
          return
        }
        const response = await comicVineApi.searchSeries(trimmed, SEARCH_PAGE_SIZE, offset)
        if (requestId !== asyncRef.current) return
        setSeriesResults((previous) =>
          append ? mergeSeriesResults(previous, response.results) : response.results
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
    [handleDirectResolution],
  )

  useEffect(() => {
    if (isOpen && threadTitle.trim() && !hasAutoSearchedRef.current) {
      hasAutoSearchedRef.current = true
      handleSearch(threadTitle)
    }
    if (!isOpen) {
      hasAutoSearchedRef.current = false
    }
  }, [isOpen, threadTitle, handleSearch])

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

  const handleSelectSeries = useCallback(
    async (series: ComicVineSeriesResult) => {
      setSelectedSeries(series)
      setStep('select-issue')
      setIsSearching(true)
      setError(null)
      const requestId = ++asyncRef.current
      try {
        const response = await comicVineApi.getSeriesIssues(series.comicvine_volume_id, series.name)
        if (requestId !== asyncRef.current) return
        setIssueCandidates(response.issues)
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
        if (requestId !== asyncRef.current) return
        setError('Failed to load issues. Please try again.')
        setIssueCandidates([])
      } finally {
        if (requestId === asyncRef.current) {
          setIsSearching(false)
        }
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
      onClose()
    } catch {
      setError('Failed to confirm identity. Please try again.')
    } finally {
      setIsConfirming(false)
    }
  }, [issueId, directIssue, selectedIssue, mode, onConfirmed, onClose])

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' && step === 'search' && query.trim()) {
        if (debounceRef.current) clearTimeout(debounceRef.current)
        handleSearch(query)
      }
    },
    [step, query, handleSearch],
  )

  const confirmSeriesName = directIssue?.series_name ?? selectedSeries?.name ?? threadTitle
  const confirmIssue = directIssue ?? selectedIssue

  return (
    <Modal
      isOpen={isOpen}
      title={step === 'search' ? 'Find ComicVine Match' : step === 'select-issue' ? 'Select Issue' : 'Confirm Match'}
      onClose={onClose}
      size="large"
    >
      <div className="space-y-4">
        {error && (
          <div className="p-3 rounded-lg bg-rose-900/30 border border-rose-700/40 text-sm text-rose-300" role="alert">
            {error}
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
              {isSearching && (
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
                {pagination.hasMore && (
                  <button
                    type="button"
                    onClick={handleLoadMore}
                    disabled={isSearching}
                    data-testid="comicvine-load-more"
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
                Search ComicVine for the correct series
              </p>
            )}
            {!isSearching && query.trim() && seriesResults.length === 0 && hasSearched && !error && (
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
                  setStep('search')
                  setSelectedSeries(null)
                  setIssueCandidates([])
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
            {isSearching ? (
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
            ) : (
              <p className="text-sm text-stone-400 text-center py-4">
                {issueNumber
                  ? `No match for #${issueNumber} in this series.`
                  : 'No issues found in this series.'}
              </p>
            )}
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
      </div>
    </Modal>
  )
}