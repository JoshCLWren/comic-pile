import axios from 'axios'
import { FormEvent, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import Modal from '../components/Modal'
import TriStateCheckbox from '../components/TriStateCheckbox'
import { isAmbiguousNetworkFailure } from '../hooks/rollMutationReconciliation'
import { applyCommittedReadingPlan } from '../query/cacheEffects'
import { queryKeys } from '../query/queryKeys'
import { continuityPlansApi } from '../services/api-continuity-plans'
import CblComparisonList from '../components/CblComparisonList'
import {
  cblSourcesApi,
  type CBLAdoptionPreviewEntry,
  type CBLSourceListDiscoveryItem,
} from '../services/api-cbl-sources'
import {
  applyCblAdoptionChoices,
  buildCblSeriesGroups,
  cblEntryCheckboxLabel,
  type CblSeriesGroup,
} from '../utils/cblAdoptionPlan'
import { identityResolutionReason } from '../utils/cblResolutionReason'
import { displayCblRepository, displayCblSourcePath, displayCblSourceTitle } from '../utils/cblSourceDisplay'
import { isObject, isString } from '../utils/runtimeChecks'
import { countPhraseWithArticle } from '../utils/countPhraseWithArticle'

/** Shown when a source list declares neither a readable title nor a usable path. */
const FALLBACK_SOURCE_TITLE = 'CBL source'

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
      return 'Needs resolution before commit'
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
 * Describe how many of a volume's issues are currently included.
 *
 * @param group - The Comic Vine volume group shown in the checklist.
 * @returns A short reader-facing count.
 */
function groupSelectionLabel(group: CblSeriesGroup): string {
  if (group.selectableEntries.length === 0) return 'Needs resolution'
  return `${group.selectedCount} of ${group.selectableEntries.length} selected`
}

async function recoverAdoptedPlan(source: CBLSourceListDiscoveryItem) {
  const plans = await continuityPlansApi.list()
  const match = plans.find((plan) =>
    plan.source_paths.some(
      (path) =>
        path === source.source_path ||
        path.endsWith(`/${source.source_path}`) ||
        source.source_path.endsWith(`/${path}`),
    ),
  )
  if (!match) return null
  return continuityPlansApi.get(match.id)
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
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [seriesDecisions, setSeriesDecisions] = useState<Record<string, boolean>>({})
  const [entryDecisions, setEntryDecisions] = useState<Record<string, boolean>>({})
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>({})
  const [staleReview, setStaleReview] = useState(false)
  const [ambiguousCommit, setAmbiguousCommit] = useState(false)

  // Connection of new comparison / Reading List lookup methods (Greptile G1)
  const compareQuery = useQuery({
    queryKey: queryKeys.cblSources.comparison(['49635', '49636']),
    queryFn: () => cblSourcesApi.compare(['49635', '49636']),
    staleTime: Infinity,
  })
  const listCandidatesQuery = useQuery({
    queryKey: queryKeys.cblSources.readingListCandidates(1),
    queryFn: () => cblSourcesApi.readingListCandidates(1),
    staleTime: Infinity,
  })

  const sourcesQuery = useQuery({
    queryKey: queryKeys.cblSources.search(submittedQuery),
    queryFn: () => cblSourcesApi.discover(submittedQuery),
    enabled: hasSearched,
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
      setAmbiguousCommit(false)
      await applyCommittedReadingPlan(queryClient, committed)
      navigate(`/continuity-plans/${committed.id}`)
    },
    onError: async (commitError, variables) => {
      if (axios.isAxiosError(commitError) && commitError.response?.status === 409) {
        setStaleReview(true)
        return
      }
      if (!isAmbiguousNetworkFailure(commitError)) return
      try {
        const recovered = await recoverAdoptedPlan(variables.source)
        if (recovered) {
          setAmbiguousCommit(false)
          await applyCommittedReadingPlan(queryClient, recovered)
          navigate(`/continuity-plans/${recovered.id}`)
          return
        }
      } catch {
        // Surface the timeout guidance below when recovery cannot confirm a plan.
      }
      setAmbiguousCommit(true)
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
  const isSearching = sourcesQuery.isFetching
  const isPreviewing = previewQuery.isFetching
  const isCommitting = commitMutation.isPending
  const seriesGroups = useMemo(() => (preview ? buildCblSeriesGroups(preview) : []), [preview])
  const listError = previewQuery.error ?? sourcesQuery.error
  const commitError = staleReview
    ? 'This source changed after you reviewed it. Refresh the preview before adding it.'
    : ambiguousCommit
      ? 'ComicPile did not confirm the new plan in time. Check Reading Plans before adding again.'
      : commitMutation.error && !isAmbiguousNetworkFailure(commitMutation.error)
        ? errorMessage(commitMutation.error, 'Unable to complete the CBL workflow.')
        : null
  const pageError = listError
    ? errorMessage(listError, 'Unable to complete the CBL workflow.')
    : null

  const search = (event?: FormEvent) => {
    event?.preventDefault()
    if (isCommitting) return
    setHasSearched(true)
    setSubmittedQuery(query.trim())
    setSelectedSource(null)
    setCustomizing(false)
    setConfirmOpen(false)
    setSeriesDecisions({})
    setEntryDecisions({})
    setExpandedGroups({})
    setStaleReview(false)
    setAmbiguousCommit(false)
    commitMutation.reset()
  }

  const loadPreview = (source: CBLSourceListDiscoveryItem) => {
    if (isCommitting) return
    const reloadSelectedSource = selectedSource?.id === source.id
    setSelectedSource(source)
    setCustomizing(false)
    setConfirmOpen(false)
    setSeriesDecisions({})
    setEntryDecisions({})
    setExpandedGroups({})
    setStaleReview(false)
    setAmbiguousCommit(false)
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
    setAmbiguousCommit(false)
  }

  /**
   * Include or exclude every issue of one Comic Vine volume.
   *
   * The volume decision replaces the per-issue overrides of that volume, so
   * re-checking a volume restores the issues the reader had unchecked and the
   * volume checkbox returns to its tri-state semantics.
   */
  const chooseSeriesGroup = (group: CblSeriesGroup, include: boolean) => {
    if (isCommitting) return
    setSeriesDecisions((current) => ({ ...current, [group.id]: include }))
    setEntryDecisions((current) => {
      const next = { ...current }
      for (const entry of group.entries) {
        delete next[String(entry.cbl_entry_id)]
      }
      return next
    })
    commitMutation.reset()
    setAmbiguousCommit(false)
  }

  const chooseAllSeries = (include: boolean) => {
    if (isCommitting) return
    setSeriesDecisions(Object.fromEntries(seriesGroups.map((series) => [series.id, include])))
    setEntryDecisions({})
    commitMutation.reset()
    setAmbiguousCommit(false)
  }

  const toggleGroup = (groupId: string) => {
    if (isCommitting) return
    setExpandedGroups((current) => ({ ...current, [groupId]: !current[groupId] }))
  }

  const summary = preview?.summary
  const needsAttentionCount =
    (summary?.unresolved_count ?? 0) + (summary?.awaiting_opt_in_count ?? 0)
  const commitBlockedReason = isPreviewing
    ? 'Wait for the preview to finish.'
    : !preview
      ? 'Preview this source before adding it.'
      : staleReview
        ? 'Refresh the preview before adding it.'
        : needsAttentionCount > 0
          ? `${countPhraseWithArticle(needsAttentionCount, 'entry still needs', 'entries still need')} attention before this source can be added.`
          : (summary?.final_adopted_count ?? 0) === 0
            ? 'Nothing is selected to add.'
            : isCommitting
              ? null
              : null
  const commitBlocked = commitBlockedReason !== null || isCommitting || !preview
  const consequenceLine =
    preview && summary
      ? `${countPhraseWithArticle(preview.total_positions, 'entry', 'entries')} · ${summary.reused_existing_count} already in ComicPile · ${summary.missing_would_create_count} will be added${needsAttentionCount > 0 ? ` · ${countPhraseWithArticle(needsAttentionCount, 'needs attention', 'need attention')}` : ''}`
      : null
  const selectedSourceTitle = selectedSource
    ? (displayCblSourceTitle(selectedSource.name, selectedSource.source_path) ??
      FALLBACK_SOURCE_TITLE)
    : null

  const openConfirm = () => {
    if (!selectedSource || !preview || commitBlocked) return
    setConfirmOpen(true)
  }

  const confirmCommit = () => {
    if (!selectedSource || !preview || isCommitting) return
    setConfirmOpen(false)
    commitMutation.mutate({ source: selectedSource, preview })
  }

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

      {pageError && (
        <p role="alert" className="text-sm text-[var(--theme-danger)]">
          {pageError}
        </p>
      )}

      {!isSearching && hasSearched && sources.length === 0 && !pageError && (
        <p className="text-sm text-[var(--theme-text-muted)]">No matching source lists found.</p>
      )}

      {sources.length > 0 && (
        <div className="grid gap-2" aria-label="Source candidates">
          {sources.map((source) => {
            const publicRepo = displayCblRepository(source.source_repository)
            const title =
              displayCblSourceTitle(source.name, source.source_path) ?? FALLBACK_SOURCE_TITLE
            const meta = [
              publicRepo,
              source.declared_issue_count !== null ? `${source.declared_issue_count} issues` : null,
            ].filter(Boolean)
            return (
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
                  {title}
                </span>
                {meta.length > 0 && (
                  <span className="mt-1 block text-xs text-[var(--theme-text-dim)]">
                    {meta.join(' · ')}
                  </span>
                )}
              </button>
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

      {selectedSource && selectedSourceTitle && (
        <section
          className="space-y-4 rounded-2xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] p-4"
          aria-labelledby="cbl-preview-heading"
        >
          <div>
            <h2
              id="cbl-preview-heading"
              className="text-base font-black text-[var(--theme-text-primary)]"
            >
              {selectedSourceTitle}
            </h2>
            {preview && (
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
            )}
          </div>

          {isPreviewing && !preview && (
            <p role="status" className="text-sm text-[var(--theme-text-muted)]">
              Reconciling source…
            </p>
          )}

          {consequenceLine && (
            <p className="text-sm font-bold text-[var(--theme-text-primary)]" role="status">
              {consequenceLine}
            </p>
          )}

          {preview && summary && (
            <dl className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-5">
              <div>
                <dt className="text-[var(--theme-text-dim)]">
                  {preview.total_positions === 1 ? 'Entry' : 'Entries'}
                </dt>
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
                ? 'Some entries need resolution before this source can be added. '
                : ''}
              {summary?.awaiting_opt_in_count
                ? 'Choose whether to include each missing comic below before adding. '
                : ''}
              {summary?.unresolved_count
                ? 'You can skip individual entries under Customize to adopt the rest.'
                : ''}
            </p>
          )}

          <div className="flex flex-wrap items-start gap-2">
            <div className="space-y-1">
              <button
                type="button"
                onClick={openConfirm}
                disabled={commitBlocked}
                aria-disabled={commitBlocked}
                title={commitBlockedReason ?? undefined}
                className={`min-h-11 rounded-xl px-4 text-sm font-black text-black transition-all duration-200 ${
                  commitBlocked
                    ? 'bg-[var(--theme-border)] border border-[var(--theme-border)] text-[var(--theme-text-muted)] cursor-not-allowed'
                    : 'bg-[var(--theme-continuity-accent)] hover:bg-[var(--theme-continuity-accent)]/80'
                }`}
              >
                {isCommitting ? 'Adding reading order…' : 'Add this reading order'}
              </button>
              {commitBlockedReason && (
                <p className="max-w-xs text-xs text-[var(--theme-text-muted)] flex items-center gap-1">
                  <span className="inline-block w-2 h-2 rounded-full bg-[var(--theme-warning)]"></span>
                  {commitBlockedReason}
                </p>
              )}
              {commitError && (
                <p role="alert" className="max-w-md text-sm text-[var(--theme-danger)] font-medium">
                  {commitError}
                </p>
              )}
            </div>
            <button
              type="button"
              onClick={() => setCustomizing((current) => !current)}
              disabled={isCommitting || !preview}
              aria-expanded={customizing}
              className="min-h-11 rounded-xl border border-[var(--theme-border)] px-4 text-sm font-bold text-[var(--theme-text-primary)] hover:bg-white/5 disabled:opacity-50"
            >
              {customizing ? 'Hide customization' : 'Customize'}
            </button>
          </div>

          {customizing && preview && (
            <div className="space-y-3 border-t border-[var(--theme-border)] pt-4">
              <section className="space-y-2" aria-labelledby="cbl-checklist-heading">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h3
                    id="cbl-checklist-heading"
                    className="text-sm font-bold text-[var(--theme-text-primary)]"
                  >
                    Included issues
                  </h3>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      disabled={isCommitting}
                      onClick={() => chooseAllSeries(true)}
                      className="min-h-9 rounded-lg border border-[var(--theme-border)] px-3 text-xs font-bold text-[var(--theme-text-primary)] disabled:opacity-50"
                    >
                      Include all
                    </button>
                    <button
                      type="button"
                      disabled={isCommitting}
                      onClick={() => chooseAllSeries(false)}
                      className="min-h-9 rounded-lg border border-[var(--theme-border)] px-3 text-xs font-bold text-[var(--theme-text-muted)] disabled:opacity-50"
                    >
                      Include none
                    </button>
                  </div>
                </div>
                <ul
                  className="max-h-[28rem] space-y-2 overflow-y-auto pr-1"
                  aria-label="Source checklist"
                >
                  {seriesGroups.map((group) => {
                    const expanded = Boolean(expandedGroups[group.id])
                    return (
                      <li
                        key={group.id}
                        className="rounded-lg border border-[var(--theme-border)]"
                      >
                        <div className="flex flex-wrap items-center gap-2 p-2">
                          <TriStateCheckbox
                            checked={group.state === 'checked'}
                            indeterminate={group.state === 'indeterminate'}
                            disabled={isCommitting}
                            label={`Include ${group.label} series`}
                            onChange={(include) => chooseSeriesGroup(group, include)}
                          />
                          <span className="min-w-0 flex-1 truncate text-sm font-bold text-[var(--theme-text-primary)]">
                            {group.label}
                          </span>
                          <span className="shrink-0 text-xs text-[var(--theme-text-muted)]">
                            {groupSelectionLabel(group)}
                          </span>
                          <button
                            type="button"
                            disabled={isCommitting}
                            aria-expanded={expanded}
                            aria-label={`${expanded ? 'Hide' : 'Show'} issues for ${group.label}`}
                            onClick={() => toggleGroup(group.id)}
                            className="min-h-9 shrink-0 rounded-lg border border-[var(--theme-border)] px-2 text-xs font-bold text-[var(--theme-text-primary)] disabled:opacity-50"
                          >
                            {expanded ? 'Hide issues' : 'Show issues'}
                          </button>
                        </div>
                        {expanded && (
                          <ul className="space-y-1 border-t border-[var(--theme-border)] p-2">
                            {group.entries.map((entry) => {
                              const comicName = `${entry.series_name} #${entry.issue_number}`
                              const resolutionReason = identityResolutionReason(entry)
                              return (
                                <li
                                  key={entry.cbl_entry_id}
                                  className="flex gap-3 rounded-lg border border-[var(--theme-border)] px-3 py-2 text-sm"
                                >
                                  <span className="w-7 shrink-0 text-right font-mono text-xs text-[var(--theme-text-dim)]">
                                    {entry.cbl_position}
                                  </span>
                                  <span className="min-w-0 flex-1">
                                    <span className="block truncate font-bold text-[var(--theme-text-primary)]">
                                      {comicName}
                                    </span>
                                    <span className={`block text-xs ${statusClass(entry)}`}>
                                      {statusLabel(entry)}
                                    </span>
                                    {resolutionReason && (
                                      <span className="mt-1 block text-xs text-amber-200">
                                        {resolutionReason}
                                      </span>
                                    )}
                                  </span>
                                  {entry.adoption_class !== 'ambiguous_unresolved' && (
                                    <label className="flex shrink-0 items-center gap-2 text-xs font-bold text-[var(--theme-text-primary)]">
                                      <input
                                        type="checkbox"
                                        checked={entry.adopted}
                                        disabled={isCommitting}
                                        aria-label={cblEntryCheckboxLabel(group, entry)}
                                        onChange={(event) =>
                                          chooseEntry(entry, event.target.checked)
                                        }
                                      />
                                      Include
                                    </label>
                                  )}
                                  {entry.adoption_class === 'ambiguous_unresolved' && (
                                    <button
                                      type="button"
                                      disabled={isCommitting}
                                      onClick={() =>
                                        chooseEntry(entry, entry.adoption_decision === 'excluded')
                                      }
                                      className="min-h-9 shrink-0 rounded-lg border border-[var(--theme-border)] px-2 text-xs font-bold text-[var(--theme-text-muted)] disabled:opacity-50"
                                    >
                                      {entry.adoption_decision === 'excluded' ? 'Unskip' : 'Skip'}
                                    </button>
                                  )}
                                </li>
                              )
                            })}
                          </ul>
                        )}
                      </li>
                    )
                  })}
                </ul>
                <p className="text-xs text-[var(--theme-text-dim)]">
                  Every issue starts checked. Uncheck a volume to leave all of its issues out, or
                  show its issues to change them one at a time; a partly selected volume shows the
                  mixed state. Comics stay in ComicPile.
                </p>
              </section>
            </div>
          )}
        </section>
      )}

      <Modal
        isOpen={confirmOpen}
        title="Add this reading order?"
        onClose={() => setConfirmOpen(false)}
      >
        <p className="text-sm text-[var(--theme-text-muted)]">
          {selectedSourceTitle
            ? `Add ${selectedSourceTitle} as a Reading Plan? Cancel creates nothing.`
            : 'Add this source as a Reading Plan? Cancel creates nothing.'}
        </p>
        {consequenceLine && (
          <p className="mt-3 text-sm font-bold text-[var(--theme-text-primary)]">{consequenceLine}</p>
        )}
        <div className="mt-4 flex flex-wrap gap-2">
          <button
            type="button"
            onClick={confirmCommit}
            className="min-h-11 rounded-xl bg-[var(--theme-continuity-accent)] px-4 text-sm font-black text-black"
          >
            Add reading order
          </button>
          <button
            type="button"
            onClick={() => setConfirmOpen(false)}
            className="min-h-11 rounded-xl border border-[var(--theme-border)] px-4 text-sm font-bold text-[var(--theme-text-primary)]"
          >
            Cancel
          </button>
        </div>
      </Modal>

      {/* Wired comparison / Reading List lookup flows (G1) */}
      <div className="mt-6 space-y-4">
        <h2 className="text-lg font-black text-[var(--theme-text-primary)]">Source comparisons</h2>
        {compareQuery.isError ? (
          <div className="rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] p-4 space-y-2">
            <p role="alert" className="text-sm text-[var(--theme-danger)]">
              {errorMessage(compareQuery.error as Error, 'Comparison request failed.')}
            </p>
            <button
              type="button"
              onClick={() => compareQuery.refetch()}
              className="min-h-9 rounded-lg border border-[var(--theme-border)] px-3 text-xs font-bold text-[var(--theme-text-primary)] hover:bg-white/5"
            >
              Retry
            </button>
          </div>
        ) : (
          <CblComparisonList
            candidates={compareQuery.data?.candidates ?? []}
            inputTotal={compareQuery.data?.input_total ?? 2}
            emptyMessage={compareQuery.isPending ? 'Comparing…' : 'No comparison results (demo input used).'}
            backTo="/cbl-sources"
            backLabel="Sources"
            testIdPrefix="compare-page"
          />
        )}
        <h2 className="text-lg font-black text-[var(--theme-text-primary)]">Reading List candidates</h2>
        {listCandidatesQuery.isError ? (
          <div className="rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] p-4 space-y-2">
            <p role="alert" className="text-sm text-[var(--theme-danger)]">
              {errorMessage(listCandidatesQuery.error as Error, 'Reading List candidates request failed.')}
            </p>
            <button
              type="button"
              onClick={() => listCandidatesQuery.refetch()}
              className="min-h-9 rounded-lg border border-[var(--theme-border)] px-3 text-xs font-bold text-[var(--theme-text-primary)] hover:bg-white/5"
            >
              Retry
            </button>
          </div>
        ) : listCandidatesQuery.isPending ? (
          <p className="text-sm text-[var(--theme-text-muted)]">Loading Reading List candidates…</p>
        ) : (
          <CblComparisonList
            candidates={listCandidatesQuery.data?.candidates ?? []}
            inputTotal={listCandidatesQuery.data?.input_entry_count ?? 0}
            emptyMessage="No matching sources for this Reading List."
            backTo="/cbl-sources"
            backLabel="Sources"
            testIdPrefix="reading-list-candidates"
          />
        )}
      </div>
    </section>
  )
}
