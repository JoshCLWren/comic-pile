import { useEffect, useRef, useState } from 'react'
import Modal from '../../components/Modal'
import type { ThreadListItem } from '../../types'
import { issuesApi } from '../../services/api-issues'
import { comicVineApi, type ComicVineSeriesResult } from '../../services/api-comicvine'
import { seriesMappingsApi, type SeriesMappingPreviewResponse } from '../../services/api-series-mappings'
import { getApiErrorDetail } from '../../utils/apiError'

interface MapSeriesDialogProps {
  thread: ThreadListItem
  onClose: () => void
  onCommitted: () => Promise<void> | void
}

type DialogStep = 'search' | 'preview' | 'done'

export default function MapSeriesDialog({ thread, onClose, onCommitted }: MapSeriesDialogProps) {
  const [step, setStep] = useState<DialogStep>('search')
  const [query, setQuery] = useState(thread.title)
  const [results, setResults] = useState<ComicVineSeriesResult[]>([])
  const [searching, setSearching] = useState(false)
  const [originIssueId, setOriginIssueId] = useState<number | null>(null)
  const [selectedSeries, setSelectedSeries] = useState<ComicVineSeriesResult | null>(null)
  const [preview, setPreview] = useState<SeriesMappingPreviewResponse | null>(null)
  const [approvedRowIds, setApprovedRowIds] = useState<Set<string>>(new Set())
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [summary, setSummary] = useState<string | null>(null)
  const asyncRef = useRef(0)

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const response = await issuesApi.list(thread.id, { page_size: 1 })
        if (!cancelled) {
          setOriginIssueId(response.issues[0]?.id ?? null)
        }
      } catch {
        if (!cancelled) setOriginIssueId(null)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [thread.id])

  const runSearch = async (value: string) => {
    const token = ++asyncRef.current
    setSearching(true)
    setError(null)
    try {
      const response = await comicVineApi.searchSeries(value, 10, 0)
      if (token === asyncRef.current) {
        setResults(response.results)
      }
    } catch (err) {
      if (token === asyncRef.current) {
        setError(getApiErrorDetail(err))
        setResults([])
      }
    } finally {
      if (token === asyncRef.current) {
        setSearching(false)
      }
    }
  }

  const handleSearch = (event: React.FormEvent) => {
    event.preventDefault()
    void runSearch(query)
  }

  const handleSelectSeries = async (series: ComicVineSeriesResult) => {
    setSelectedSeries(series)
    setError(null)
    if (originIssueId == null) {
      setError('This thread has no issues to anchor a mapping preview.')
      return
    }
    setBusy(true)
    try {
      const response = await seriesMappingsApi.preview({
        origin_issue_id: originIssueId,
        provider: 'comicvine',
        provider_series_external_id: String(series.comicvine_volume_id),
      })
      setPreview(response)
      setApprovedRowIds(new Set((response.rows ?? []).filter((row) => row.default_selected).map((row) => row.row_id)))
      setStep('preview')
    } catch (err) {
      setError(getApiErrorDetail(err))
    } finally {
      setBusy(false)
    }
  }

  const toggleRow = (rowId: string) => {
    setApprovedRowIds((previous) => {
      const next = new Set(previous)
      if (next.has(rowId)) {
        next.delete(rowId)
      } else {
        next.add(rowId)
      }
      return next
    })
  }

  const handleCommit = async () => {
    if (!preview || !preview.preview_token) {
      setError('Preview is not available for this series.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      const result = await seriesMappingsApi.commit({
        preview_token: preview.preview_token,
        idempotency_key: `map-series-${thread.id}-${Date.now()}`,
        approved_row_ids: Array.from(approvedRowIds),
      })
      setSummary(
        `Mapped ${result.confirmed_issue_ids?.length ?? 0} issue(s). ` +
          `${result.already_confirmed_issue_ids?.length ?? 0} already confirmed. ` +
          `${result.needs_review_issue_ids?.length ?? 0} need review.`,
      )
      setStep('done')
      await onCommitted()
    } catch (err) {
      setError(getApiErrorDetail(err))
    } finally {
      setBusy(false)
    }
  }

  const handleBack = () => {
    setStep('search')
    setPreview(null)
    setApprovedRowIds(new Set())
    setSelectedSeries(null)
    setError(null)
  }

  return (
    <Modal isOpen={true} title={`Map Series: ${thread.title}`} onClose={onClose} size="large">
      <div className="space-y-4">
        {error && (
          <p role="alert" className="text-sm text-[var(--theme-danger)]">
            {error}
          </p>
        )}

        {step === 'search' && (
          <>
            <form onSubmit={handleSearch} className="flex gap-2">
              <input
                type="text"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                aria-label="Search ComicVine series"
                className="flex-1 rounded-lg border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-3 py-2 text-sm text-[var(--theme-text-primary)]"
              />
              <button
                type="submit"
                disabled={searching}
                className="rounded-lg bg-[var(--theme-primary-action)] px-4 py-2 text-sm font-bold text-white hover:bg-[var(--theme-primary-action-hover)] disabled:opacity-50"
              >
                {searching ? 'Searching…' : 'Search'}
              </button>
            </form>
            <ul className="space-y-2">
              {results.map((series) => (
                <li key={series.comicvine_volume_id}>
                  <button
                    type="button"
                    onClick={() => void handleSelectSeries(series)}
                    disabled={busy}
                    className="w-full rounded-lg border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-3 py-2 text-left text-sm text-[var(--theme-text-primary)] hover:bg-[var(--theme-bg-hover)] disabled:opacity-50"
                  >
                    <span className="font-bold">{series.name}</span>
                    <span className="text-[var(--theme-text-muted)]">
                      {' · '}
                      {[series.publisher, series.start_year, series.issue_count ? `${series.issue_count} issues` : null]
                        .filter(Boolean)
                        .join(' · ')}
                    </span>
                  </button>
                </li>
              ))}
              {results.length === 0 && !searching && (
                <li className="text-sm text-[var(--theme-text-muted)]">No series results yet.</li>
              )}
            </ul>
          </>
        )}

        {step === 'preview' && preview && (
          <>
            <p className="text-sm text-[var(--theme-text-muted)]">
              {selectedSeries?.name} · {preview.provider_series?.publisher ?? 'Unknown publisher'} ·{' '}
              {preview.counts.safe_exact_match} safe match(es), {preview.counts.needs_review_ambiguous + preview.counts.needs_review_conflict}{' '}
              review row(s), {preview.counts.unresolved} unresolved, {preview.counts.excluded_special} excluded,{' '}
              {preview.counts.already_confirmed} already confirmed.
            </p>
            {preview.counts.safe_exact_match === 0 && (
              <p className="text-sm text-[var(--theme-text-muted)]">
                No safe exact mappings are available for this series. Every row stays
                untouched and remains available for issue-level correction.
              </p>
            )}
            <ul className="max-h-64 space-y-1 overflow-y-auto">
              {(preview.rows ?? []).map((row) => (
                <li key={row.row_id} className="flex items-center gap-2 text-sm text-[var(--theme-text-primary)]">
                  {row.classification === 'safe_exact_match' ? (
                    <input
                      type="checkbox"
                      aria-label={`Approve ${row.row_id}`}
                      checked={approvedRowIds.has(row.row_id)}
                      onChange={() => toggleRow(row.row_id)}
                    />
                  ) : (
                    <span aria-hidden="true" className="inline-block w-4" />
                  )}
                  <span className="font-medium">#{row.issue_number}</span>
                  <span className="text-[var(--theme-text-muted)]">{row.classification.replaceAll('_', ' ')}</span>
                  {row.reason && <span className="text-[var(--theme-text-dim)]">— {row.reason}</span>}
                </li>
              ))}
            </ul>
            <div className="flex justify-end gap-3">
              <button
                type="button"
                onClick={handleBack}
                className="rounded-lg border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-4 py-2 text-sm font-semibold text-[var(--theme-text-primary)]"
              >
                Back
              </button>
              <button
                type="button"
                disabled={busy || approvedRowIds.size === 0}
                onClick={() => void handleCommit()}
                className="rounded-lg bg-[var(--theme-primary-action)] px-4 py-2 text-sm font-bold text-white hover:bg-[var(--theme-primary-action-hover)] disabled:opacity-50"
              >
                {busy ? 'Committing…' : `Commit ${approvedRowIds.size} safe mapping(s)`}
              </button>
            </div>
          </>
        )}

        {step === 'done' && (
          <>
            <p className="text-sm text-[var(--theme-text-primary)]">{summary}</p>
            <p className="text-sm text-[var(--theme-text-muted)]">
              Remaining rows were left untouched for issue-level correction.
            </p>
            <div className="flex justify-end">
              <button
                type="button"
                onClick={onClose}
                className="rounded-lg bg-[var(--theme-primary-action)] px-4 py-2 text-sm font-bold text-white hover:bg-[var(--theme-primary-action-hover)]"
              >
                Done
              </button>
            </div>
          </>
        )}
      </div>
    </Modal>
  )
}
