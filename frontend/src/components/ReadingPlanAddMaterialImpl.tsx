import axios from 'axios'
import { FormEvent, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { applyCommittedReadingPlan } from '../query/cacheEffects'
import { queryKeys } from '../query/queryKeys'
import { isObject, isString } from '../utils/runtimeChecks'
import {
  cblSourcesApi,
  type CBLAdoptionCommitResult,
  type CBLAdoptionPreview,
  type CBLAdoptionPreviewEntry,
  type CBLSourceListDiscoveryItem,
} from '../services/api-cbl-sources'

interface ReadingPlanAddMaterialProps {
  planId: number
  planName: string
  defaultOpen?: boolean
  onCommitted?: (plan: CBLAdoptionCommitResult) => void
}

function statusLabel(entry: CBLAdoptionPreviewEntry): string {
  switch (entry.adoption_decision) {
    case 'included_existing':
      return entry.read_status === 'read' ? 'Already in ComicPile · read' : 'Already in ComicPile'
    case 'would_create_missing':
      return 'Missing · selected to add'
    case 'awaiting_opt_in':
      return 'Missing · choose whether to add'
    case 'excluded':
      return 'Excluded'
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

function errorMessage(error: unknown, fallback: string): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail
    if (isString(detail) && detail.trim()) return detail
    if (detail && isObject(detail) && 'message' in detail && isString(detail.message)) {
      return detail.message
    }
  }
  return error instanceof Error && error.message ? error.message : fallback
}

export default function ReadingPlanAddMaterial({
  planId,
  planName,
  defaultOpen = false,
  onCommitted,
}: ReadingPlanAddMaterialProps) {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(defaultOpen)
  const [query, setQuery] = useState(planName)
  const [submittedQuery, setSubmittedQuery] = useState(defaultOpen ? planName : '')
  const [selectedSource, setSelectedSource] = useState<CBLSourceListDiscoveryItem | null>(null)
  const [seriesDecisions, setSeriesDecisions] = useState<Record<string, boolean>>({})
  const [entryDecisions, setEntryDecisions] = useState<Record<string, boolean>>({})
  const [hasSearched, setHasSearched] = useState(defaultOpen)
  const [staleReview, setStaleReview] = useState(false)
  const sourcesQuery = useQuery({
    queryKey: queryKeys.cblSources.search(submittedQuery),
    queryFn: () => cblSourcesApi.discover(submittedQuery),
    enabled: open && hasSearched,
  })
  const hasChoices =
    Object.keys(seriesDecisions).length > 0 || Object.keys(entryDecisions).length > 0
  const previewQuery = useQuery({
    queryKey: selectedSource
      ? queryKeys.cblSources.adoptionPlan(
          selectedSource.id,
          seriesDecisions,
          entryDecisions,
        )
      : queryKeys.cblSources.preview(0),
    queryFn: () => {
      if (!selectedSource) throw new Error('Choose a CBL source first.')
      return hasChoices
        ? cblSourcesApi.plan(selectedSource.id, { series_decisions: seriesDecisions, entry_decisions: entryDecisions })
        : cblSourcesApi.preview(selectedSource.id)
    },
    enabled: selectedSource !== null,
    placeholderData: (previous) => previous,
  })
  const commitMutation = useMutation({
    mutationFn: ({
      source,
      reviewed,
    }: {
      source: CBLSourceListDiscoveryItem
      reviewed: CBLAdoptionPreview
    }) => cblSourcesApi.commit(source.id, planId, reviewed, {
      series_decisions: seriesDecisions,
      entry_decisions: entryDecisions,
    }),
    onSuccess: async (committed) => {
      await applyCommittedReadingPlan(queryClient, committed)
      onCommitted?.(committed)
    },
    onError: (commitError) => {
      if (axios.isAxiosError(commitError) && commitError.response?.status === 409) {
        setStaleReview(true)
      }
    },
  })

  const sources = sourcesQuery.data ?? []
  const preview = previewQuery.data ?? null
  const result: CBLAdoptionCommitResult | undefined = commitMutation.data
  const isSearching = sourcesQuery.isFetching
  const isPreviewing = previewQuery.isFetching
  const isCommitting = commitMutation.isPending
  const activeError = commitMutation.error ?? previewQuery.error ?? sourcesQuery.error
  const error = staleReview
    ? 'This source changed after you reviewed it. Refresh the preview before adding material.'
    : activeError
      ? errorMessage(activeError, 'Unable to complete the CBL workflow.')
      : null

  const search = async (event?: FormEvent) => {
    event?.preventDefault()
    setHasSearched(true)
    setSubmittedQuery(query.trim())
    setSelectedSource(null)
    setSeriesDecisions({})
    setEntryDecisions({})
    setStaleReview(false)
    commitMutation.reset()
  }

  const loadPreview = (source: CBLSourceListDiscoveryItem) => {
    const reloadSelectedSource = selectedSource?.id === source.id
    setSelectedSource(source)
    setSeriesDecisions({})
    setEntryDecisions({})
    setStaleReview(false)
    commitMutation.reset()
    if (reloadSelectedSource) void previewQuery.refetch()
  }

  const chooseEntry = (entry: CBLAdoptionPreviewEntry, include: boolean) => {
    setEntryDecisions((current) => ({
      ...current,
      [String(entry.cbl_entry_id)]: include,
    }))
    commitMutation.reset()
  }

  const commit = () => {
    if (!selectedSource || !preview) return
    commitMutation.mutate({ source: selectedSource, reviewed: preview })
  }

  const toggleOpen = () => {
    const next = !open
    setOpen(next)
    if (next && !hasSearched) {
      setSubmittedQuery(query.trim())
      setHasSearched(true)
    }
  }

  const commitBlocked =
    !preview ||
    preview.summary.unresolved_count > 0 ||
    preview.summary.awaiting_opt_in_count > 0 ||
    preview.summary.final_adopted_count === 0 ||
    staleReview ||
    isCommitting ||
    isPreviewing
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

  const chooseSeries = (seriesId: string, include: boolean) => {
    setSeriesDecisions((current) => ({ ...current, [seriesId]: include }))
    commitMutation.reset()
  }

  const chooseAllSeries = (include: boolean) => {
    setSeriesDecisions(
      Object.fromEntries(seriesGroups.map((series) => [series.id, include])),
    )
    setEntryDecisions({})
    commitMutation.reset()
  }

  return (
    <section className="rounded-2xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] p-4" aria-labelledby="add-material-heading">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 id="add-material-heading" className="text-sm font-black text-[var(--theme-text-primary)]">Add material</h2>
          <p className="mt-1 text-xs text-[var(--theme-text-muted)]">
            Find source-backed reading material, review it, then decide what belongs in this Reading Plan.
          </p>
        </div>
        <button
          type="button"
          onClick={toggleOpen}
          className="min-h-11 rounded-xl border border-[var(--theme-border)] px-4 text-sm font-bold text-[var(--theme-text-primary)] hover:bg-white/5"
          aria-expanded={open}
        >
          {open ? 'Close' : 'Add from CBL'}
        </button>
      </div>

      {open && (
        <div className="mt-4 space-y-4 border-t border-[var(--theme-border)] pt-4">
          <form onSubmit={search} className="flex flex-col gap-2 sm:flex-row">
            <label className="sr-only" htmlFor="reading-plan-source-search">Search source lists</label>
            <input
              id="reading-plan-source-search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search source lists"
              maxLength={200}
              className="min-h-11 flex-1 rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-card)] px-3 text-[var(--theme-text-primary)]"
            />
            <button
              type="submit"
              disabled={isSearching}
              className="min-h-11 rounded-xl bg-[var(--theme-continuity-accent)] px-4 text-sm font-black text-black disabled:opacity-50"
            >
              {isSearching ? 'Searching…' : 'Search'}
            </button>
          </form>

          {error && <p role="alert" className="text-sm text-red-300">{error}</p>}

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
                  className={`rounded-xl border p-3 text-left ${selectedSource?.id === source.id ? 'border-[var(--theme-continuity-accent)]' : 'border-[var(--theme-border)]'} hover:bg-white/5`}
                >
                  <span className="block text-sm font-bold text-[var(--theme-text-primary)]">{source.name}</span>
                  <span className="mt-1 block text-xs text-[var(--theme-text-muted)]">{source.source_path}</span>
                  <span className="mt-1 block text-xs text-[var(--theme-text-dim)]">
                    {source.source_repository}{source.declared_issue_count !== null ? ` · ${source.declared_issue_count} issues` : ''}
                  </span>
                </button>
              ))}
            </div>
          )}

          {staleReview && selectedSource && (
            <button
              type="button"
              onClick={() => {
                setStaleReview(false)
                void previewQuery.refetch()
              }}
              className="min-h-11 rounded-xl border border-[var(--theme-border)] px-4 text-sm font-bold text-[var(--theme-text-primary)] hover:bg-white/5"
            >
              Refresh preview
            </button>
          )}

          {isPreviewing && <p role="status" className="text-sm text-[var(--theme-text-muted)]">Reconciling source…</p>}

          {preview && selectedSource && (
            <section className="space-y-3 rounded-xl border border-[var(--theme-border)] p-3" aria-labelledby="source-preview-heading">
              <div>
                <h3 id="source-preview-heading" className="text-sm font-black text-[var(--theme-text-primary)]">{selectedSource.name}</h3>
                <p className="mt-1 text-xs text-[var(--theme-text-muted)]">{preview.source.source_path}</p>
                <p className="mt-1 text-xs text-[var(--theme-text-dim)]">{preview.source.source_repository} · revision {preview.source.revision_sha.slice(0, 8)}</p>
              </div>

              <dl className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
                <div><dt className="text-[var(--theme-text-dim)]">Existing</dt><dd className="font-bold text-[var(--theme-text-primary)]">{preview.summary.reused_existing_count}</dd></div>
                <div><dt className="text-[var(--theme-text-dim)]">Selected missing</dt><dd className="font-bold text-[var(--theme-text-primary)]">{preview.summary.missing_would_create_count}</dd></div>
                <div><dt className="text-[var(--theme-text-dim)]">Needs choice</dt><dd className="font-bold text-[var(--theme-text-primary)]">{preview.summary.awaiting_opt_in_count}</dd></div>
                <div><dt className="text-[var(--theme-text-dim)]">Unresolved</dt><dd className="font-bold text-[var(--theme-text-primary)]">{preview.summary.unresolved_count}</dd></div>
              </dl>

              <section className="space-y-2" aria-labelledby="series-decisions-heading">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h4 id="series-decisions-heading" className="text-xs font-black uppercase tracking-widest text-[var(--theme-text-primary)]">Series choices</h4>
                  <div className="flex gap-2">
                    <button type="button" onClick={() => chooseAllSeries(true)} className="min-h-9 rounded-lg border border-[var(--theme-border)] px-3 text-xs font-bold text-[var(--theme-text-primary)]">Include all</button>
                    <button type="button" onClick={() => chooseAllSeries(false)} className="min-h-9 rounded-lg border border-[var(--theme-border)] px-3 text-xs font-bold text-[var(--theme-text-muted)]">Include none</button>
                  </div>
                </div>
                <div className="grid gap-2 sm:grid-cols-2">
                  {seriesGroups.map((series) => (
                    <div key={series.id} className="flex items-center justify-between gap-2 rounded-lg border border-[var(--theme-border)] p-2">
                      <span className="min-w-0 truncate text-xs font-bold text-[var(--theme-text-primary)]">{series.name}</span>
                      <div className="flex shrink-0 gap-1" role="group" aria-label={`${series.name} series choice`}>
                        <button type="button" aria-pressed={seriesDecisions[series.id] === true} onClick={() => chooseSeries(series.id, true)} className="min-h-9 rounded-lg border border-[var(--theme-border)] px-2 text-xs text-[var(--theme-text-primary)]">Include</button>
                        <button type="button" aria-pressed={seriesDecisions[series.id] === false} onClick={() => chooseSeries(series.id, false)} className="min-h-9 rounded-lg border border-[var(--theme-border)] px-2 text-xs text-[var(--theme-text-muted)]">Exclude</button>
                      </div>
                    </div>
                  ))}
                </div>
                <p className="text-xs text-[var(--theme-text-dim)]">Individual choices below override a series choice.</p>
              </section>

              <ol className="max-h-[28rem] space-y-1 overflow-y-auto pr-1" aria-label="Reconciled source order">
                {preview.entries.map((entry) => (
                  <li key={entry.cbl_entry_id} className="flex gap-3 rounded-lg border border-[var(--theme-border)] px-3 py-2 text-sm">
                    <span className="w-7 shrink-0 text-right font-mono text-xs text-[var(--theme-text-dim)]">{entry.cbl_position}</span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-bold text-[var(--theme-text-primary)]">{entry.series_name} #{entry.issue_number}</span>
                      <span className={`block text-xs ${statusClass(entry)}`}>{statusLabel(entry)}</span>
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
                  </li>
                ))}
              </ol>

              {preview.summary.unresolved_count > 0 && (
                <p className="text-xs text-amber-300">Resolve ambiguous identities before adding this source.</p>
              )}
              {preview.summary.awaiting_opt_in_count > 0 && (
                <p className="text-xs text-[var(--theme-text-muted)]">Choose whether to include each missing comic before committing.</p>
              )}

              <button
                type="button"
                onClick={commit}
                disabled={commitBlocked}
                className="min-h-11 rounded-xl bg-[var(--theme-continuity-accent)] px-4 text-sm font-black text-black disabled:opacity-50"
              >
                {isCommitting ? 'Adding material…' : 'Add selected material'}
              </button>
            </section>
          )}

          {result && (
            <p role="status" className="text-sm text-emerald-300">
              Added material to this Reading Plan · created {result.created_positions.length} · reused {result.reused_positions.length}.
            </p>
          )}
        </div>
      )}
    </section>
  )
}
