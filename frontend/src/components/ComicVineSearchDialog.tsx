import { useState, useCallback, useRef, useEffect } from 'react'
import Modal from './Modal'
import {
  comicVineApi,
  type ComicVineSeriesResult,
  type ComicVineIssueCandidate,
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
  onConfirmed: () => void
}

type DialogStep = 'search' | 'select-issue' | 'confirm'

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
  const [isSearching, setIsSearching] = useState(false)
  const [isConfirming, setIsConfirming] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [hasSearched, setHasSearched] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

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
      setError(null)
      setHasSearched(false)
    }
  }, [isOpen, threadTitle])

  const hasAutoSearchedRef = useRef(false)

  const handleSearch = useCallback(async (searchQuery: string) => {
    if (!searchQuery.trim()) {
      setSeriesResults([])
      setHasSearched(false)
      return
    }
    setIsSearching(true)
    setError(null)
    setHasSearched(true)
    try {
      const response = await comicVineApi.searchSeries(searchQuery.trim(), 10)
      setSeriesResults(response.results)
    } catch {
      setError('Failed to search ComicVine. Please try again.')
      setSeriesResults([])
    } finally {
      setIsSearching(false)
    }
  }, [])

  useEffect(() => {
    if (isOpen && threadTitle.trim() && !hasAutoSearchedRef.current) {
      hasAutoSearchedRef.current = true
      handleSearch(threadTitle)
    }
    if (!isOpen) {
      hasAutoSearchedRef.current = false
    }
  }, [isOpen, threadTitle, handleSearch])

  const handleQueryChange = useCallback((value: string) => {
    setQuery(value)
    if (!value.trim()) {
      setHasSearched(false)
      setSeriesResults([])
    }
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => handleSearch(value), 350)
  }, [handleSearch])

  const handleSelectSeries = useCallback(async (series: ComicVineSeriesResult) => {
    setSelectedSeries(series)
    setStep('select-issue')
    setIsSearching(true)
    setError(null)
    try {
      const response = await comicVineApi.getSeriesIssues(series.comicvine_volume_id, series.name)
      setIssueCandidates(response.issues)
    } catch {
      setError('Failed to load issues. Please try again.')
      setIssueCandidates([])
    } finally {
      setIsSearching(false)
    }
  }, [])

  const handleSelectIssue = useCallback((issue: ComicVineIssueCandidate) => {
    setSelectedIssue(issue)
    setStep('confirm')
  }, [])

  const handleConfirm = useCallback(async () => {
    if (!issueId || !selectedIssue) return
    setIsConfirming(true)
    setError(null)
    try {
      if (mode === 'replace') {
        await comicVineApi.replaceIdentity(issueId, selectedIssue.comicvine_issue_id)
      } else {
        await comicVineApi.confirmIdentity(issueId, selectedIssue.comicvine_issue_id)
      }
      onConfirmed()
      onClose()
    } catch {
      setError('Failed to confirm identity. Please try again.')
    } finally {
      setIsConfirming(false)
    }
  }, [issueId, selectedIssue, mode, onConfirmed, onClose])

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && step === 'search' && query.trim()) {
      if (debounceRef.current) clearTimeout(debounceRef.current)
      handleSearch(query)
    }
  }, [step, query, handleSearch])

  return (
    <Modal
      isOpen={isOpen}
      title={step === 'search' ? 'Find ComicVine Match' : step === 'select-issue' ? 'Select Issue' : 'Confirm Match'}
      onClose={onClose}
    >
      <div className="space-y-4">
        {error && (
          <div className="p-3 rounded-lg bg-rose-900/30 border border-rose-700/40 text-sm text-rose-300" role="alert">
            {error}
          </div>
        )}

        {step === 'search' && (
          <>
            <p className="text-xs text-stone-400">
              Search for the correct ComicVine series for <span className="font-bold text-stone-200">{threadTitle}</span>
            </p>
            <div className="relative">
              <input
                ref={inputRef}
                type="text"
                value={query}
                onChange={(e) => handleQueryChange(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Search series title..."
                className="w-full min-h-11 rounded-xl px-4 pr-10 text-sm text-stone-100 bg-stone-800 border border-stone-600 focus:border-amber-500 focus:ring-1 focus:ring-amber-500 outline-none transition"
              />
              {isSearching && (
                <div className="absolute right-3 top-1/2 -translate-y-1/2">
                  <div className="w-4 h-4 border-2 border-amber-500/30 border-t-amber-500 rounded-full animate-spin" />
                </div>
              )}
            </div>
            {seriesResults.length > 0 && (
              <div className="space-y-1.5 max-h-72 overflow-y-auto overscroll-contain">
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
                      <div className="min-w-0">
                        <p className="text-sm font-bold text-stone-100 group-hover:text-amber-300 transition truncate">
                          {series.name}
                        </p>
                        <p className="text-[11px] text-stone-500">
                          {seriesMetaText(series)}
                        </p>
                      </div>
                    </div>
                  </button>
                ))}
              </div>
            )}
            {!isSearching && !query.trim() && (
              <p className="text-xs text-stone-500 text-center py-4">
                Type a series name to search ComicVine
              </p>
            )}
            {!isSearching && query.trim() && seriesResults.length === 0 && !hasSearched && (
              <p className="text-xs text-stone-500 text-center py-4">
                Search ComicVine for the correct series
              </p>
            )}
            {!isSearching && query.trim() && seriesResults.length === 0 && hasSearched && !error && (
              <p className="text-xs text-stone-400 text-center py-4">
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
                className="text-xs text-amber-500 hover:text-amber-400 font-bold"
              >
                ← Back to search
              </button>
              <span className="text-xs text-stone-500">·</span>
              <span className="text-xs text-stone-400 truncate">
                {selectedSeries.name}
                {seriesMetaText(selectedSeries) && ` (${seriesMetaText(selectedSeries)})`}
              </span>
            </div>
            {isSearching ? (
              <div className="flex justify-center py-8">
                <div className="w-5 h-5 border-2 border-amber-500/30 border-t-amber-500 rounded-full animate-spin" />
              </div>
            ) : issueCandidates.length > 0 ? (
              <div className="space-y-1.5 max-h-80 overflow-y-auto overscroll-contain">
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
                          {issue.name && <span className="font-normal text-stone-400 ml-2">{issue.name}</span>}
                        </p>
                        {issue.cover_date && (
                          <p className="text-[10px] text-stone-500">{issue.cover_date}</p>
                        )}
                      </div>
                    </div>
                  </button>
                ))}
              </div>
            ) : (
              <p className="text-xs text-stone-500 text-center py-4">
                No issues found in this series.
              </p>
            )}
          </>
        )}

        {step === 'confirm' && selectedIssue && selectedSeries && (
          <>
            <button
              type="button"
              onClick={() => {
                setStep('select-issue')
                setSelectedIssue(null)
              }}
              className="text-xs text-amber-500 hover:text-amber-400 font-bold"
            >
              ← Back to issues
            </button>
            <div className="p-4 rounded-xl bg-stone-800/50 border border-stone-700/50 space-y-3">
              <p className="text-[10px] font-black uppercase tracking-wider text-stone-500">Selected match</p>
              <div className="flex items-start gap-3">
{selectedIssue.image_url && (
          <ImageWithLoading
            src={optimizedImageUrl(selectedIssue.image_url, 240) ?? selectedIssue.image_url}
            srcSet={optimizedImageSrcSet(selectedIssue.image_url, [96, 240]) ?? undefined}
            sizes="64px"
            alt=""
            className="w-16 h-22 object-cover rounded-lg shrink-0"
          />
        )}
                <div className="min-w-0">
                  <p className="text-sm font-bold text-stone-100">{selectedSeries.name}</p>
                  <p className="text-xs text-stone-300">
                    {selectedIssue.issue_number ? `#${selectedIssue.issue_number}` : ''}
                    {selectedIssue.name && ` — ${selectedIssue.name}`}
                  </p>
                  {selectedIssue.cover_date && (
                    <p className="text-[10px] text-stone-500 mt-1">{selectedIssue.cover_date}</p>
                  )}
                </div>
              </div>
              <p className="text-[10px] text-stone-500">
                This will confirm <span className="text-stone-300">{threadTitle} #{issueNumber}</span> maps to this ComicVine issue.
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
