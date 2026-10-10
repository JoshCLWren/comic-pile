import axios from 'axios'
import { FormEvent, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { applyCommittedReadingPlan } from '../query/cacheEffects'
import { queryKeys } from '../query/queryKeys'
import { isObject, isString } from '../utils/runtimeChecks'
import {
  cblSourcesApi,
  type CBLAdoptionPreviewEntry,
  type CBLSourceListDiscoveryItem,
} from '../services/api-cbl-sources'

function statusLabel(entry: CBLAdoptionPreviewEntry): string {
  switch (entry.adoption_decision) {
    case 'included_existing':
      if (entry.resolution_status === 'resolved_via_title_number_fallback') {
        return 'Already in ComicPile · matched by title'
      }
      return entry.read_status === 'read' ? 'Already in ComicPile · read' : 'Already in ComicPile'
    case 'would_create_missing':
      return 'Missing · will be added'
    case 'awaiting_opt_in':
      return 'Missing · choose whether to add'
    case 'excluded':
      return entry.adoption_class === 'ambiguous_unresolved' ? 'Skipped' : 'Excluded'
    case 'unresolved':
      return 'Needs identity resolution'
  }
}

function statusClass(entry: CBLAdoptionPreviewEntry): string {
  if (entry.adoption_decision === 'included_existing') return 'text-emerald-300'
  if (entry.adoption_decision === 'would_create_missing') return 'text-sky-300'
  if (entry.adoption_decision === 'unresolved') return 'text-amber-300'
  return 'text-[var(--theme-text-muted)]'
}

function errorMessage(error: Error, fallback: string): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail
    if (isString(detail) && detail.trim()) return detail
    if (detail && isObject(detail) && 'message' in detail && isString(detail.message)) {
      return detail.message
    }
  }
  return error instanceof Error && error.message ? error.message : fallback
}

/**
 * Standalone CBL browser: find a trusted reading-order source, preview its
 * consequences without mutation, then adopt it into a canonical Reading Plan
 * with one decision. Selecting the source is the data entry — the reader never
 * re-types titles, issue numbers, or source order.
 */
export default function CblBrowserPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [query, setQuery] = useState('')
  const [submittedQuery, setSubmittedQuery] = useState('')
  const [hasSearched, setHasSearched] = useState(false)
  const [selectedSource, setSelectedSource] = useState<CBLSourceListDiscoveryItem | null>(null)
  const [customizing, setCustomizing] = useState(false)
  const [seriesDecisions, setSeriesDecisions] = useState<Record<string, boolean>>({})
  const [entryDecisions, setEntryDecisions] = useState<Record<string, boolean>>({})
  const [staleReview, setStaleReview] = useState(false)

  const sourcesQuery = useQuery({
    queryKey: queryKeys.cblSources.search(submittedQuery),
    queryFn: () => cblSourcesApi.discover(submittedQuery),
    enabled: hasSearched,
  })

  const hasChoices =
    Object.keys(seriesDecisions).length > 0 || Object.keys(entryDecisions).length > 0
  const previewQuery = useQuery({
    queryKey: selectedSource
      ? queryKeys.cblSources.adoptionPlan(selectedSource.id, seriesDecisions, entryDecisions)
      : queryKeys.cblSources.preview(0),
    queryFn: () => {
      if (!selectedSource) throw new Error('Choose a CBL source first.')
      return hasChoices
        ? cblSourcesApi.plan(selectedSource.id, {
            series_decisions: seriesDecisions,
            entry_decisions: entryDecisions,
          })
        : cblSourcesApi.preview(selectedSource.id)
    },
    enabled: selectedSource !== null,
    placeholderData: (previous) => previous,
  })

  const commitMutation = useMutation({
    mutationFn: ({
      source,
      preview,
    }: {
      source: CBLSourceListDiscoveryItem
      preview: NonNullable<typeof previewQuery.data>
    }) =>
      cblSourcesApi.commitNew(source.id, preview, {
        series_decisions: seriesDecisions,
        entry_decisions: entryDecisions,
      }),
    onSuccess: async (committed) => {
      await applyCommittedReadingPlan(queryClient, committed)
      navigate(`/continuity-plans/${committed.id}`)
    },
    onError: (commitError) => {
      if (axios.isAxiosError(commitError) && commitError.response?.status === 409) {
        setStaleReview(true)
      }
    },
  })

  const sources = sourcesQuery.data ?? []
  const preview = previewQuery.data ?? null
  const isSearching = sourcesQuery.isFetching
  const isPreviewing = previewQuery.isFetching
  const isCommitting = commitMutation.isPending
  const activeError = commitMutation.error ?? previewQuery.error ?? sourcesQuery.error
  const error = staleReview
    ? 'This source changed after you reviewed it. Refresh the preview before adding it.'
    : activeError
      ? errorMessage(activeError, 'Unable to complete the CBL workflow.')
      : null

  const search = (event?: FormEvent) => {
    event?.preventDefault()
    if (isCommitting) return
    setHasSearched(true)
    setSubmittedQuery(query.trim())
    setSelectedSource(null)
    setCustomizing(false)
    setSeriesDecisions({})
    setEntryDecisions({})
    setStaleReview(false)
    commitMutation.reset()
  }

  const loadPreview = (source: CBLSourceListDiscoveryItem) => {
    if (isCommitting) return
    const reloadSelectedSource = selectedSource?.id === source.id
    setSelectedSource(source)
    setCustomizing(false)
    setSeriesDecisions({})
    setEntryDecisions({})
    setStaleReview(false)
    commitMutation.reset()
    if (reloadSelectedSource) void previewQuery.refetch()
  }

  const chooseEntry = (entry: CBLAdoptionPreviewEntry, include: boolean) => {
    if (isCommitting) return
    setEntryDecisions((current) => ({
      ...current,
      [String(entry.cbl_entry_id)]: include,
    }))
    commitMutation.reset()
  }

  const chooseSeries = (seriesId: string, include: boolean) => {
    if (isCommitting) return
    setSeriesDecisions((current) => ({ ...current, [seriesId]: include }))
    commitMutation.reset()
  }

  const chooseAllSeries = (include: boolean) => {
    if (isCommitting) return
    setSeriesDecisions(Object.fromEntries(seriesGroups.map((series) => [series.id, include])))
    setEntryDecisions({})
    commitMutation.reset()
  }

  const commit = () => {
    if (!selectedSource || !preview || isCommitting) return
    commitMutation.mutate({ source: selectedSource, preview })
  }

  const seriesGroups = preview
    ? Array.from(
        new Map(
          preview.entries.map((entry) => [
            entry.series_group_id,
            { id: entry.series_group_id, name: entry.series_name },
          ]),
        ).values(),
      )
    : []

  const summary = preview?.summary
  const needsAttentionCount =
    (summary?.unresolved_count ?? 0) + (summary?.awaiting_opt_in_count ?? 0)
  const commitBlocked =
    !preview ||
    needsAttentionCount > 0 ||
    (summary?.final_adopted_count ?? 0) === 0 ||
    staleReview ||
    isCommitting ||
    isPreviewing
  const consequenceLine =
    preview && summary
      ? `${preview.total_positions} entries · ${summary.reused_existing_count} already in ComicPile · ${summary.missing_would_create_count} will be added${needsAttentionCount > 0 ? ` · ${needsAttentionCount} need attention` : ''}`
      : null

  return (
    <section className="space-y-5" aria-labelledby="cbl-browser-heading">
      <header>
        <h1 id="cbl-browser-heading" className="text-2xl font-black text-[var(--theme-text-primary)]">
          CBL Sources
        </h1>
        <p className="mt-2 max-w-2xl text-sm text-[var(--theme-text-muted)]">
          Browse trusted reading-order sources. Selecting a source is the data entry — preview
          what it would do, then add it as a Reading Plan in one step.
        </p>
      </header>

      <form onSubmit={search} className="flex flex-col gap-2 sm:flex-row">
        <label className="sr-only" htmlFor="cbl-browser-search">
          Search source lists
        </label>
        <input
          id="cbl-browser-search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search source lists"
          maxLength={200}
          disabled={isCommitting}
          className="min-h-11 flex-1 rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-3 text-[var(--theme-text-primary)] disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={isSearching || isCommitting}
          className="min-h-11 rounded-xl bg-[var(--theme-continuity-accent)] px-4 text-sm font-black text-black disabled:opacity-50"
        >
          {isSearching ? 'Searching…' : 'Search'}
        </button>
      </form>

      {error && (
        <p role="alert" className="text-sm text-red-300">
          {error}
        </p>
      )}

      {!isSearching && hasSearched && sources.length === 0 && !error && (
        <p className="text-sm text-[var(--theme-text-muted)]">No matching source lists found.</p>
      )}

      {sources.length > 0 && (
        <div className="grid gap-2" aria-label="Source candidates">
          {sources.map((source) => (
            <button
              key={source.id}
              type="button"
              onClick={() => loadPreview(source)}
              disabled={isCommitting}
              className={`rounded-xl border p-3 text-left disabled:opacity-50 ${
                selectedSource?.id === source.id
                  ? 'border-[var(--theme-continuity-accent)]'
                  : 'border-[var(--theme-border)]'
              } hover:bg-white/5`}
            >
              <span className="block text-sm font-bold text-[var(--theme-text-primary)]">
                {source.name}
              </span>
              <span className="mt-1 block text-xs text-[var(--theme-text-muted)]">
                {source.source_path}
              </span>
              <span className="mt-1 block text-xs text-[var(--theme-text-dim)]">
                {source.source_repository}
                {source.declared_issue_count !== null
                  ? ` · ${source.declared_issue_count} issues`
                  : ''}
              </span>
            </button>
          ))}
        </div>
      )}

      {staleReview && selectedSource && (
        <button
          type="button"
          disabled={isCommitting}
          onClick={() => {
            setStaleReview(false)
            void previewQuery.refetch()
          }}
          className="min-h-11 rounded-xl border border-[var(--theme-border)] px-4 text-sm font-bold text-[var(--theme-text-primary)] hover:bg-white/5 disabled:opacity-50"
        >
          Refresh preview
        </button>
      )}

      {isPreviewing && !preview && (
        <p role="status" className="text-sm text-[var(--theme-text-muted)]">
          Reconciling source…
        </p>
      )}

      {preview && selectedSource && (
        <section
          className="space-y-4 rounded-2xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] p-4"
          aria-labelledby="cbl-preview-heading"
        >
          <div>
            <h2
              id="cbl-preview-heading"
              className="text-base font-black text-[var(--theme-text-primary)]"
            >
              {selectedSource.name}
            </h2>
            <p className="mt-1 text-xs text-[var(--theme-text-muted)]">
              {preview.source.source_path}
            </p>
            <p className="mt-1 text-xs text-[var(--theme-text-dim)]">
              {preview.source.source_repository} · revision {preview.source.revision_sha.slice(0, 8)}
            </p>
          </div>

          {consequenceLine && (
            <p className="text-sm font-bold text-[var(--theme-text-primary)]" role="status">
              {consequenceLine}
            </p>
          )}

          {summary && (
            <dl className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-5">
              <div>
                <dt className="text-[var(--theme-text-dim)]">Entries</dt>
                <dd className="font-bold text-[var(--theme-text-primary)]">
                  {preview.total_positions}
                </dd>
              </div>
              <div>
                <dt className="text-[var(--theme-text-dim)]">Already in ComicPile</dt>
                <dd className="font-bold text-[var(--theme-text-primary)]">
                  {summary.reused_existing_count}
                </dd>
              </div>
              <div>
                <dt className="text-[var(--theme-text-dim)]">Will be added</dt>
                <dd className="font-bold text-[var(--theme-text-primary)]">
                  {summary.missing_would_create_count}
                </dd>
              </div>
              <div>
                <dt className="text-[var(--theme-text-dim)]">Need attention</dt>
                <dd className="font-bold text-[var(--theme-text-primary)]">
                  {needsAttentionCount}
                </dd>
              </div>
              <div>
                <dt className="text-[var(--theme-text-dim)]">Final plan size</dt>
                <dd className="font-bold text-[var(--theme-text-primary)]">
                  {summary.final_adopted_count}
                </dd>
              </div>
            </dl>
          )}

          {needsAttentionCount > 0 && (
            <p className="text-xs text-amber-300">
              {summary?.unresolved_count
                ? 'Some entries need identity resolution before this source can be added. '
                : ''}
              {summary?.awaiting_opt_in_count
                ? 'Choose whether to include each missing comic below before adding. '
                : ''}
              {summary?.unresolved_count
                ? 'You can skip individual entries under Customize to adopt the rest.'
                : ''}
            </p>
          )}

          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={commit}
              disabled={commitBlocked}
              className="min-h-11 rounded-xl bg-[var(--theme-continuity-accent)] px-4 text-sm font-black text-black disabled:opacity-50"
            >
              {isCommitting ? 'Adding reading order…' : 'Add this reading order'}
            </button>
            <button
              type="button"
              onClick={() => setCustomizing((current) => !current)}
              disabled={isCommitting}
              aria-expanded={customizing}
              className="min-h-11 rounded-xl border border-[var(--theme-border)] px-4 text-sm font-bold text-[var(--theme-text-primary)] hover:bg-white/5 disabled:opacity-50"
            >
              {customizing ? 'Hide customization' : 'Customize'}
            </button>
          </div>

          {customizing && (
            <div className="space-y-3 border-t border-[var(--theme-border)] pt-4">
              <section className="space-y-2" aria-labelledby="cbl-series-decisions-heading">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h3
                    id="cbl-series-decisions-heading"
                    className="text-xs font-black uppercase tracking-widest text-[var(--theme-text-primary)]"
                  >
                    Series choices
                  </h3>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      disabled={isCommitting || isPreviewing}
                      onClick={() => chooseAllSeries(true)}
                      className="min-h-9 rounded-lg border border-[var(--theme-border)] px-3 text-xs font-bold text-[var(--theme-text-primary)] disabled:opacity-50"
                    >
                      Include all
                    </button>
                    <button
                      type="button"
                      disabled={isCommitting || isPreviewing}
                      onClick={() => chooseAllSeries(false)}
                      className="min-h-9 rounded-lg border border-[var(--theme-border)] px-3 text-xs font-bold text-[var(--theme-text-muted)] disabled:opacity-50"
                    >
                      Include none
                    </button>
                  </div>
                </div>
                <div className="grid gap-2 sm:grid-cols-2">
                  {seriesGroups.map((series) => (
                    <div
                      key={series.id}
                      className="flex items-center justify-between gap-2 rounded-lg border border-[var(--theme-border)] p-2"
                    >
                      <span className="min-w-0 truncate text-xs font-bold text-[var(--theme-text-primary)]">
                        {series.name}
                      </span>
                      <div
                        className="flex shrink-0 gap-1"
                        role="group"
                        aria-label={`${series.name} series choice`}
                      >
                        <button
                          type="button"
                          disabled={isCommitting || isPreviewing}
                          aria-pressed={seriesDecisions[series.id] === true}
                          onClick={() => chooseSeries(series.id, true)}
                          className="min-h-9 rounded-lg border border-[var(--theme-border)] px-2 text-xs text-[var(--theme-text-primary)] disabled:opacity-50"
                        >
                          Include
                        </button>
                        <button
                          type="button"
                          disabled={isCommitting || isPreviewing}
                          aria-pressed={seriesDecisions[series.id] === false}
                          onClick={() => chooseSeries(series.id, false)}
                          className="min-h-9 rounded-lg border border-[var(--theme-border)] px-2 text-xs text-[var(--theme-text-muted)] disabled:opacity-50"
                        >
                          Exclude
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
                <p className="text-xs text-[var(--theme-text-dim)]">
                  Excluding a series affects this Reading Plan only — it never deletes comics from
                  ComicPile.
                </p>
              </section>

              <ol className="max-h-[28rem] space-y-1 overflow-y-auto pr-1" aria-label="Reconciled source order">
                {preview.entries.map((entry) => (
                  <li
                    key={entry.cbl_entry_id}
                    className="flex gap-3 rounded-lg border border-[var(--theme-border)] px-3 py-2 text-sm"
                  >
                    <span className="w-7 shrink-0 text-right font-mono text-xs text-[var(--theme-text-dim)]">
                      {entry.cbl_position}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-bold text-[var(--theme-text-primary)]">
                        {entry.series_name} #{entry.issue_number}
                      </span>
                      <span className={`block text-xs ${statusClass(entry)}`}>
                        {statusLabel(entry)}
                      </span>
                    </span>
                    {entry.adoption_class !== 'ambiguous_unresolved' && (
                      <label className="flex shrink-0 items-center gap-2 text-xs font-bold text-[var(--theme-text-primary)]">
                        <input
                          type="checkbox"
                          checked={entry.adopted}
                          disabled={isPreviewing || isCommitting}
                          onChange={(event) => chooseEntry(entry, event.target.checked)}
                        />
                        Include
                      </label>
                    )}
                    {entry.adoption_class === 'ambiguous_unresolved' && (
                      <button
                        type="button"
                        disabled={isPreviewing || isCommitting}
                        onClick={() =>
                          chooseEntry(entry, entry.adoption_decision === 'excluded')
                        }
                        className="min-h-9 shrink-0 rounded-lg border border-[var(--theme-border)] px-2 text-xs font-bold text-[var(--theme-text-muted)] disabled:opacity-50"
                      >
                        {entry.adoption_decision === 'excluded' ? 'Unskip' : 'Skip'}
                      </button>
                    )}
                  </li>
                ))}
              </ol>
            </div>
          )}
        </section>
      )}
    </section>
  )
}
