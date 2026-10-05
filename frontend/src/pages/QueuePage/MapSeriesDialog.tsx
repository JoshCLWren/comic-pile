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

/** Readable phrasing for a backend classification code. */
function classificationLabel(classification: string): string {
  return classification.replaceAll('_', ' ')
}

/** Count plus its correctly pluralized noun, so copy never reads "1 items". */
function countLabel(count: number, singular: string, plural: string): string {
  return `${count} ${count === 1 ? singular : plural}`
}

/**
 * Sentences for the conflict codes the series-mapping commit endpoint returns
 * instead of an unwrapped snake_case code.
 */
const COMMIT_CONFLICT_MESSAGES = new Map<string, string>([
  [
    'preview_stale',
    'This preview no longer matches the current issue data. Search for the series again to refresh it.',
  ],
  ['preview_expired', 'This preview expired. Search for the series again to get a fresh preview.'],
  [
    'confirmed_mapping_conflict',
    'One of these issues already carries a different confirmed ComicVine identity, so nothing was changed. Correct that issue individually.',
  ],
  [
    'idempotency_conflict',
    'This repair was already submitted with different rows. Search for the series again to start a new repair.',
  ],
  ['invalid_approved_row', 'One of the selected rows is no longer safe to map, so nothing was changed.'],
  ['provider_unavailable', 'ComicVine is unavailable right now, so the series could not be loaded. Try again later.'],
])

/**
 * Why no safe scope could be built, stated in product terms.
 *
 * The backend returns an empty, zero-count plan rather than an error when it
 * cannot scope the series safely, so the dialog has to say so itself instead of
 * implying the user simply selected a series with no matches.
 */
function scopeUnavailableMessage(basis: string | null | undefined): string {
  if (basis === 'insufficient_non_thread_evidence') {
    return 'ComicPile could not scope this series safely from the issue identity it already has. Nothing was changed, and every issue stays available for individual correction.'
  }
  return 'ComicPile could not scope this series safely right now. Nothing was changed, and every issue stays available for individual correction.'
}

/** Turn a documented conflict code into a sentence, keeping the raw detail otherwise. */
function commitErrorMessage(error: unknown): string {
  const detail = getApiErrorDetail(error)
  return COMMIT_CONFLICT_MESSAGES.get(detail) ?? detail
}

/**
 * Short stable digest of a commit request's material facts.
 *
 * The commit endpoint replays its receipt for an identical idempotency key and
 * rejects a reused key whose approved rows changed, so the key must be derived
 * from the preview token plus the approved rows. That keeps a retry of the same
 * request on one key while every different repair — including a later dialog
 * session for the same thread, which gets a different preview token — gets its
 * own.
 */
function shortDigest(value: string): string {
  let hash = 2166136261
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index)
    hash = Math.imul(hash, 16777619)
  }
  return (hash >>> 0).toString(16)
}

export default function MapSeriesDialog({ thread, onClose, onCommitted }: MapSeriesDialogProps) {
  const [step, setStep] = useState<DialogStep>('search')
  const [query, setQuery] = useState(thread.title)
  const [results, setResults] = useState<ComicVineSeriesResult[]>([])
  const [searching, setSearching] = useState(false)
  const [originIssueId, setOriginIssueId] = useState<number | null>(null)
  const [anchorPending, setAnchorPending] = useState(true)
  const [selectedSeries, setSelectedSeries] = useState<ComicVineSeriesResult | null>(null)
  const [preview, setPreview] = useState<SeriesMappingPreviewResponse | null>(null)
  const [approvedRowIds, setApprovedRowIds] = useState<Set<string>>(new Set())
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [summary, setSummary] = useState<string | null>(null)
  const [refreshFailed, setRefreshFailed] = useState(false)
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
      } finally {
        if (!cancelled) setAnchorPending(false)
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
    if (anchorPending) {
      setError('Still loading this series. Try again in a moment.')
      return
    }
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
      setError(commitErrorMessage(err))
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
      setError(scopeUnavailableMessage(preview?.scope.basis))
      return
    }
    const approved = Array.from(approvedRowIds).sort()
    const idempotencyKey = `map-series-${thread.id}-${shortDigest(`${preview.preview_token}|${approved.join(',')}`)}`
    setBusy(true)
    setError(null)
    setRefreshFailed(false)
    let committed = false
    try {
      const result = await seriesMappingsApi.commit({
        preview_token: preview.preview_token,
        idempotency_key: idempotencyKey,
        approved_row_ids: approved,
      })
      committed = true
      setSummary(
        `${countLabel(result.confirmed_issue_ids?.length ?? 0, 'issue mapped', 'issues mapped')}. ` +
          `${countLabel(result.already_confirmed_issue_ids?.length ?? 0, 'issue already', 'issues already')} confirmed. ` +
          `${countLabel(result.needs_review_issue_ids?.length ?? 0, 'issue still', 'issues still')} need review.`,
      )
      setStep('done')
    } catch (err) {
      setError(commitErrorMessage(err))
    } finally {
      setBusy(false)
    }
    // A queue refresh failure must not be reported as a failed repair: the
    // mappings are already committed, so the summary stays authoritative and
    // the rejection is contained instead of escaping as an unhandled promise.
    if (committed) {
      try {
        await onCommitted()
      } catch {
        setRefreshFailed(true)
      }
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
                    disabled={busy || anchorPending}
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
              {results.length > 0 && anchorPending && (
                <li className="text-sm text-[var(--theme-text-muted)]">Preparing this series…</li>
              )}
              {results.length === 0 && !searching && (
                <li className="text-sm text-[var(--theme-text-muted)]">No series results yet.</li>
              )}
            </ul>
          </>
        )}

        {step === 'preview' && preview && (
          <>
            <p className="text-sm text-[var(--theme-text-muted)]">
              {selectedSeries?.name} · {preview.provider_series?.publisher ?? 'Unknown publisher'}
            </p>
            <p className="text-sm text-[var(--theme-text-muted)]">
              {[
                countLabel(preview.counts.safe_exact_match, 'safe match', 'safe matches'),
                countLabel(
                  preview.counts.needs_review_ambiguous + preview.counts.needs_review_conflict,
                  'issue needs review',
                  'issues need review',
                ),
                countLabel(preview.counts.unresolved, 'unresolved issue', 'unresolved issues'),
                countLabel(preview.counts.excluded_special, 'excluded special', 'excluded specials'),
                countLabel(preview.counts.already_confirmed, 'already confirmed', 'already confirmed'),
              ].join(' · ')}
            </p>
            {preview.scope.status === 'available' && preview.counts.safe_exact_match === 0 && (
              <p className="text-sm text-[var(--theme-text-muted)]">
                No safe exact mappings are available for this series. Every row stays
                untouched and remains available for issue-level correction.
              </p>
            )}
            {preview.scope.status !== 'available' && (
              <p role="status" className="text-sm text-[var(--theme-text-muted)]">
                {scopeUnavailableMessage(preview.scope.basis)}
              </p>
            )}
            <ul className="max-h-64 space-y-1 overflow-y-auto">
              {(preview.rows ?? []).map((row) => (
                <li key={row.row_id} className="flex items-center gap-2 text-sm text-[var(--theme-text-primary)]">
                  {row.classification === 'safe_exact_match' ? (
                    <input
                      type="checkbox"
                      aria-label={`Approve #${row.issue_number} ${classificationLabel(row.classification)}`}
                      checked={approvedRowIds.has(row.row_id)}
                      onChange={() => toggleRow(row.row_id)}
                    />
                  ) : (
                    <span aria-hidden="true" className="inline-block w-4" />
                  )}
                  <span className="font-medium">#{row.issue_number}</span>
                  <span className="text-[var(--theme-text-muted)]">{classificationLabel(row.classification)}</span>
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
                {busy
                  ? 'Committing…'
                  : `Commit ${countLabel(approvedRowIds.size, 'safe mapping', 'safe mappings')}`}
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
            {refreshFailed && (
              <p role="status" className="text-sm text-[var(--theme-text-muted)]">
                The repair was saved, but the queue could not refresh it yet. Reload the
                queue to see the updated mapping status.
              </p>
            )}
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
