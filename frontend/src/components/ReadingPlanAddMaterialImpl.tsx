import axios from 'axios'
import { FormEvent, useEffect, useMemo, useState } from 'react'
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
import { applyCblAdoptionChoices } from '../utils/cblAdoptionPlan'
import { displayCblRepository, displayCblSourcePath, displayCblSourceTitle } from '../utils/cblSourceDisplay'

interface ReadingPlanAddMaterialProps {
  planId: number
  planName: string
  defaultOpen?: boolean
  commitDisabled?: boolean
  onCommitted?: (plan: CBLAdoptionCommitResult) => void
  onCommitPendingChange?: (isPending: boolean) => void
}

function statusLabel(entry: CBLAdoptionPreviewEntry): string {
  if (entry.collection_excluded) {
    return entry.collection_exclusion_reason === 'collection_identity_requires_review'
      ? 'Volume identity needs review before collection exclusions can be checked'
      : 'Excluded from your collection'
  }
  switch (entry.adoption_decision) {
    case 'included_existing':
      return entry.read_status === 'read'
        ? 'Already in ComicPile · read'
        : 'Already in ComicPile · reuse existing'
    case 'would_create_missing':
      return 'Missing · importable (new comic)'
    case 'awaiting_opt_in':
      return 'Missing · choose: include or exclude'
    case 'excluded':
      return 'Excluded'
    case 'unresolved':
      return 'Needs identity resolution'
  }
}

function statusClass(entry: CBLAdoptionPreviewEntry): string {
  if (entry.adoption_decision === 'included_existing') return 'text-[var(--theme-success)]'
  if (entry.adoption_decision === 'would_create_missing') return 'text-sky-300'
  if (entry.adoption_decision === 'unresolved') return 'text-[var(--theme-warning)]'
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

export default function ReadingPlanAddMaterial({
  planId,
  planName,
  defaultOpen = false,
  commitDisabled = false,
  onCommitted,
  onCommitPendingChange,
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
  const previewQuery = useQuery({
    queryKey: selectedSource
      ? queryKeys.cblSources.preview(selectedSource.id)
      : queryKeys.cblSources.preview(0),
    queryFn: () => {
      if (!selectedSource) throw new Error('Choose a CBL source first.')
      return cblSourcesApi.preview(selectedSource.id)
    },
    enabled: selectedSource !== null,
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
  const hasChoices =
    Object.keys(seriesDecisions).length > 0 || Object.keys(entryDecisions).length > 0
  const preview = useMemo(
    () => {
      if (!previewQuery.data) return null
      return hasChoices
        ? applyCblAdoptionChoices(previewQuery.data, seriesDecisions, entryDecisions)
        : previewQuery.data
    },
    [previewQuery.data, seriesDecisions, entryDecisions, hasChoices],
  )
  const result: CBLAdoptionCommitResult | undefined = commitMutation.data
  const isSearching = sourcesQuery.isFetching
  const isPreviewing = previewQuery.isFetching
  const isCommitting = commitMutation.isPending
  useEffect(() => {
    onCommitPendingChange?.(isCommitting)
    return () => onCommitPendingChange?.(false)
  }, [isCommitting, onCommitPendingChange])
  const activeError = commitMutation.error ?? previewQuery.error ?? sourcesQuery.error
  const error = staleReview
    ? 'This source changed after you reviewed it. Refresh the preview before adding material.'
    : activeError
      ? errorMessage(activeError, 'Unable to complete the CBL workflow.')
      : null

  const search = async (event?: FormEvent) => {
    event?.preventDefault()
    if (isCommitting) return
    setHasSearched(true)
    setSubmittedQuery(query.trim())
    setSelectedSource(null)
    setSeriesDecisions({})
    setEntryDecisions({})
    setStaleReview(false)
    commitMutation.reset()
  }

  const loadPreview = (source: CBLSourceListDiscoveryItem) => {
    if (isCommitting) return
    const reloadSelectedSource = selectedSource?.id === source.id
    setSelectedSource(source)
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

  const commit = () => {
    if (!selectedSource || !preview || commitDisabled || isCommitting) return
    commitMutation.mutate({ source: selectedSource, reviewed: preview })
  }

  const toggleOpen = () => {
    if (isCommitting) return
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
    commitDisabled ||
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
    if (isCommitting) return
    setSeriesDecisions((current) => ({ ...current, [seriesId]: include }))
    commitMutation.reset()
  }

  const chooseAllSeries = (include: boolean) => {
    if (isCommitting) return
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
          disabled={isCommitting}
          className="min-h-11 rounded-xl border border-[var(--theme-border)] px-4 text-sm font-bold text-[var(--theme-text-primary)] hover:bg-white/5 disabled:opacity-50"
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

          {error && <p role="alert" className="text-sm text-red-300">{error}</p>}

          {!isSearching && hasSearched && sources.length === 0 && !error && (
            <p className="text-sm text-[var(--theme-text-muted)]">No matching source lists found.</p>
          )}

          {sources.length > 0 && (
            <div className="grid gap-2" aria-label="Source candidates">
              {sources.map((source) => {
                const publicPath = displayCblSourcePath(source.source_path)
                const publicRepo = displayCblRepository(source.source_repository)
                const sourceTitle = displayCblSourceTitle(source.name, source.source_path) ?? 'Reading order'
                const meta = [
                  source.declared_issue_count !== null ? `${source.declared_issue_count} issues` : null,
                ].filter(Boolean)
                return (
                  <div key={source.id} role="group" aria-label={`Source ${sourceTitle}`} className="min-w-0 space-y-1">
                    <button
                      type="button"
                      onClick={() => loadPreview(source)}
                      disabled={isCommitting}
                      className={`w-full rounded-xl border p-3 text-left disabled:opacity-50 ${selectedSource?.id === source.id ? 'border-[var(--theme-continuity-accent)]' : 'border-[var(--theme-border)]'} hover:bg-white/5`}
                    >
                      <span className="block text-sm font-bold text-[var(--theme-text-primary)]">{sourceTitle}</span>{' '}
                      {meta.length > 0 && (
                        <span className="mt-1 block text-xs text-[var(--theme-text-dim)]">{meta.join(' · ')}</span>
                      )}
                    </button>
                    {(publicPath || publicRepo) && (
                      <details className="text-xs text-[var(--theme-text-dim)]">
                        <summary className="cursor-pointer font-bold text-[var(--theme-text-muted)]">Source details</summary>
                        <div className="mt-2 space-y-1 break-words">
                          {publicPath && <p>{publicPath}</p>}
                          {publicRepo && <p>{publicRepo}</p>}
                        </div>
                      </details>
                    )}
                  </div>
                )
              })}
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

          {isPreviewing && <p role="status" className="text-sm text-[var(--theme-text-muted)]">Reconciling source…</p>}

          {preview && selectedSource && (
            <section className="space-y-3 rounded-xl border border-[var(--theme-border)] p-3" aria-labelledby="source-preview-heading">
              <div>
                <h3 id="source-preview-heading" className="text-sm font-black text-[var(--theme-text-primary)]">{displayCblSourceTitle(selectedSource.name, selectedSource.source_path) ?? 'Reading order'}</h3>
                <details className="mt-2">
                  <summary className="cursor-pointer text-xs font-bold text-[var(--theme-text-muted)]">
                    Source details
                  </summary>
                  <div className="mt-2 space-y-1 text-xs text-[var(--theme-text-dim)]">
                    {displayCblSourcePath(preview.source.source_path) && (
                      <p>{displayCblSourcePath(preview.source.source_path)}</p>
                    )}
                    {displayCblRepository(preview.source.source_repository) && (
                      <p>{displayCblRepository(preview.source.source_repository)}</p>
                    )}
                    <p>Revision {preview.source.revision_sha.slice(0, 8)}</p>
                  </div>
                </details>
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
                    <button type="button" disabled={isCommitting || isPreviewing} onClick={() => chooseAllSeries(true)} className="min-h-9 rounded-lg border border-[var(--theme-border)] px-3 text-xs font-bold text-[var(--theme-text-primary)] disabled:opacity-50">Include all series</button>
                    <button type="button" disabled={isCommitting || isPreviewing} onClick={() => chooseAllSeries(false)} className="min-h-9 rounded-lg border border-[var(--theme-border)] px-3 text-xs font-bold text-[var(--theme-text-muted)] disabled:opacity-50">Exclude all series</button>
                  </div>
                </div>
                <div className="grid gap-2 sm:grid-cols-2">
                  {seriesGroups.map((series) => (
                    <div key={series.id} className="flex items-center justify-between gap-2 rounded-lg border border-[var(--theme-border)] p-2">
                      <span className="min-w-0 truncate text-xs font-bold text-[var(--theme-text-primary)]">{series.name}</span>
                      <div className="flex shrink-0 gap-1" role="group" aria-label={`${series.name} series choice`}>
                        <button type="button" disabled={isCommitting || isPreviewing} aria-pressed={seriesDecisions[series.id] === true} onClick={() => chooseSeries(series.id, true)} className="min-h-9 rounded-lg border border-[var(--theme-border)] px-2 text-xs text-[var(--theme-text-primary)] disabled:opacity-50">Include</button>
                        <button type="button" disabled={isCommitting || isPreviewing} aria-pressed={seriesDecisions[series.id] === false} onClick={() => chooseSeries(series.id, false)} className="min-h-9 rounded-lg border border-[var(--theme-border)] px-2 text-xs text-[var(--theme-text-muted)] disabled:opacity-50">Exclude</button>
                      </div>
                    </div>
                  ))}
                </div>
                <p className="text-xs text-[var(--theme-text-dim)]">
                  Series-level choices apply to all entries in that series group. Individual entry choices{' '}
                  <span className="font-medium">override</span> a series choice. Comics stay in ComicPile.
                </p>
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
                          disabled={isCommitting || entry.collection_excluded}
                          aria-label={`Include ${entry.series_name} #${entry.issue_number}`}
                          onChange={(event) => chooseEntry(entry, event.target.checked)}
                        />
                        <span className="font-medium">Include</span>
                      </label>
                    )}
                  </li>
                ))}
              </ol>

              {preview.summary.unresolved_count > 0 && (
                <p className="text-xs text-[var(--theme-warning)]">
                  <strong>Resolve unresolved comics or exclude their series</strong> before committing.
                </p>
              )}
              {preview.summary.awaiting_opt_in_count > 0 && (
                <p className="text-xs text-[var(--theme-text-muted)]">
                  Missing comics not yet confirmed as importable. Choose whether to{' '}
                  <span className="font-medium">include</span> or{' '}
                  <span className="font-medium">exclude</span>{' '}each one before committing.
                </p>
              )}
              {commitDisabled && (
                <p className="text-xs text-[var(--theme-text-dim)]">
                  Save or cancel unsaved planner changes before adding material.
                </p>
              )}
              <p className="text-xs text-[var(--theme-text-dim)]">
                Three adoption choices per entry:{' '}
                <span className="font-medium text-[var(--theme-success)]">Include</span> – add this comic (reuse existing or importable new){' '}
                <span className="font-medium text-[var(--theme-text-muted)]">Exclude</span> – leave this comic out{' '}
                <span className="font-medium text-[var(--theme-warning)]">Unresolved</span> – needs identity resolution first
              </p>

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
