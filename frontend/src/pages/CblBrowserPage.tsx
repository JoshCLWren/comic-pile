import axios from 'axios'
import { FormEvent, Fragment, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import Modal from '../components/Modal'
import ReadingGraphOverlapDialog from '../components/ReadingGraphOverlapDialog'
import ReadingGraphSummary from '../components/ReadingGraphSummary'
import TriStateCheckbox from '../components/TriStateCheckbox'
import { isAmbiguousNetworkFailure } from '../hooks/rollMutationReconciliation'
import { applyCommittedReadingPlan } from '../query/cacheEffects'
import { queryKeys } from '../query/queryKeys'
import { continuityPlansApi } from '../services/api-continuity-plans'
import { CblSourceDetailPanel } from '../components/CblSourceDetailPanel'
import {
  cblSourcesApi,
  type CBLAdoptionPreviewEntry,
  type CBLSourceListDiscoveryItem,
} from '../services/api-cbl-sources'
import {
  buildReadingGraphRequest,
  hasGenuineOverlap,
  overlapChoicePayload,
  readingGraphSeriesLabel,
  unresolvedOverlaps,
  withLocalChoices,
  type ReadingGraphChoices,
} from '../utils/readingGraphOverlaps'
import {
  readingGraphApi,
  type ReadingGraphOverlapChoiceId,
  type ReadingGraphPreview,
} from '../services/api-reading-graph'
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

/**
 * One catalog page. The API caps pages at 100; 50 keeps a folder's folders and
 * sources above the fold on a phone without hiding the total result count.
 */
const PAGE_SIZE = 50

/** Translate a browse failure into reader-facing copy and a recovery action. */
function catalogErrorState(error: Error): {
  message: string
  recover: 'browse-root' | 'retry'
} {
  if (axios.isAxiosError(error)) {
    const status = error.response?.status
    if (status === 404) {
      return {
        message: 'This folder is no longer in the shared CBL catalog.',
        recover: 'browse-root',
      }
    }
    if (status === 400) {
      return {
        message: 'That CBL folder path is not valid. Browse the catalog from the top.',
        recover: 'browse-root',
      }
    }
    if (status === 503) {
      return {
        message: 'The shared CBL catalog is temporarily unavailable. Try again in a moment.',
        recover: 'retry',
      }
    }
  }
  return {
    message: errorMessage(error, 'Unable to load the shared CBL catalog.'),
    recover: 'retry',
  }
}

/** Count sources without inventing a plural. */
function sourceCountLabel(count: number): string {
  return `${count} ${count === 1 ? 'source' : 'sources'}`
}

/** Build the in-app URL for one browse position, excluding any open preview. */
function browseHref(folder: string, query: string, page: number): string {
  const params = new URLSearchParams()
  if (folder) params.set('folder', folder)
  if (query) params.set('q', query)
  if (page > 1) params.set('page', String(page))
  const search = params.toString()
  return search ? `/cbl-sources?${search}` : '/cbl-sources'
}

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
  if (entry.adoption_decision === 'included_existing') return 'text-[var(--theme-success)]'
  if (entry.adoption_decision === 'would_create_missing') return 'text-[var(--theme-text-primary)]'
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
  const location = useLocation()
  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()

  // The browse position lives in the URL so preview opens in place and Back
  // restores the same folder, search, and page.
  const folder = searchParams.get('folder')?.trim() ?? ''
  const submittedQuery = searchParams.get('q')?.trim() ?? ''
  const requestedPage = Number.parseInt(searchParams.get('page') ?? '', 10)
  const page = Number.isInteger(requestedPage) && requestedPage > 0 ? requestedPage : 1
  // A `list` query parameter opens one shared source list in place, so a
  // comparison result can link straight to the source detail it names.
  const requestedListId = searchParams.get('list')
  const parsedListId = requestedListId ? Number.parseInt(requestedListId, 10) : Number.NaN
  const deepLinkedListId = Number.isInteger(parsedListId) && parsedListId > 0 ? parsedListId : null

  const [queryDraft, setQueryDraft] = useState(submittedQuery)
  const [customizing, setCustomizing] = useState(false)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [seriesDecisions, setSeriesDecisions] = useState<Record<string, boolean>>({})
  const [entryDecisions, setEntryDecisions] = useState<Record<string, boolean>>({})
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>({})
  const [staleReview, setStaleReview] = useState(false)
  const [ambiguousCommit, setAmbiguousCommit] = useState(false)
  /**
   * Series-level answers for the prospective graph. Keyed by the server's
   * stable overlap identity; restored from saved decisions on reopen.
   */
  const [overlapChoices, setOverlapChoices] = useState<ReadingGraphChoices>({})
  const [graphDialogOpen, setGraphDialogOpen] = useState(false)
  /** Whether finishing the questionnaire should continue into the add confirmation. */
  const [graphDialogContinuesAdd, setGraphDialogContinuesAdd] = useState(false)
  /**
   * Source id of the current or most recent commit attempt. Commit callbacks
   * compare it with the viewed source so a settled Add never rewrites another
   * source's view, and a stale settled result gets discarded.
   */
  const [commitSourceId, setCommitSourceId] = useState<number | null>(null)
  /** The deep-linked source currently on screen, read by late-settling commit callbacks. */
  const viewedSourceIdRef = useRef<number | null>(null)
  const graphPreviewRef = useRef<ReadingGraphPreview | null>(null)

  // Keep the visible search field aligned with the URL, including browser Back.
  useEffect(() => {
    setQueryDraft(submittedQuery)
  }, [submittedQuery])

  // Late-settling commit callbacks read this mirror instead of a stale closure
  // so they can tell whether the reader still looks at the source they added.
  useEffect(() => {
    viewedSourceIdRef.current = deepLinkedListId
  }, [deepLinkedListId])

  useEffect(() => {
    setCustomizing(false)
    setConfirmOpen(false)
    setSeriesDecisions({})
    setEntryDecisions({})
    setExpandedGroups({})
    setStaleReview(false)
    setAmbiguousCommit(false)
    setOverlapChoices({})
    setGraphDialogOpen(false)
    setGraphDialogContinuesAdd(false)
    // A commit still running belongs to the reader, not to whichever source
    // Back/Forward just re-opened: keep it tracked so the pending Add stays
    // blocked, and only discard a settled result (its callbacks check the
    // view before they navigate or surface errors).
    if (!commitMutation.isPending) commitMutation.reset()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deepLinkedListId])

  /**
   * Browse the shared catalog immediately: entering the page shows the root
   * folders and sources without requiring a search submission.
   */
  const browseQuery = useQuery({
    queryKey: queryKeys.cblSources.browse(folder, submittedQuery, page),
    queryFn: () =>
      cblSourcesApi.browse({ folder, query: submittedQuery, page, pageSize: PAGE_SIZE }),
    placeholderData: keepPreviousData,
  })
  const browsePage = browseQuery.data ?? null
  const selectedSource =
    deepLinkedListId !== null
      ? (browsePage?.items.find((item) => item.id === deepLinkedListId) ?? null)
      : null

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
        overlap_decisions: overlapChoicePayload(graphQuery.data ?? null, overlapChoices),
      }),
    onSuccess: async (committed, variables) => {
      // The write is real no matter which source the view shows, so the
      // caches must learn the committed plan. The reader's next step, instead,
      // belongs to the view they were on: pressing Back or Forward while the
      // request ran must not be hijacked when it completes.
      const stillViewing = viewedSourceIdRef.current === variables.source.id
      await applyCommittedReadingPlan(queryClient, committed)
      if (stillViewing) {
        setAmbiguousCommit(false)
        navigate(`/continuity-plans/${committed.id}`)
      }
    },
    onError: async (commitError, variables) => {
      // Surface stale or failed writes only to the view that made them.
      if (viewedSourceIdRef.current !== variables.source.id) return
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

  // Discard a settled commit that belongs to a different source than the one
  // on screen: its callbacks no longer own this view, and a stale result must
  // not linger into the next Add.
  const { isPending: commitIsPending, reset: resetCommitMutation } = commitMutation
  useEffect(() => {
    if (!commitIsPending && commitSourceId !== null && commitSourceId !== deepLinkedListId) {
      resetCommitMutation()
      setCommitSourceId(null)
    }
  }, [commitSourceId, deepLinkedListId, commitIsPending, resetCommitMutation])

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
  const isPreviewing = previewQuery.isFetching
  const isCommitting = commitMutation.isPending
  const seriesGroups = useMemo(() => (preview ? buildCblSeriesGroups(preview) : []), [preview])

  /**
   * The graph preview follows the reader's checklist and answers. `preview` is
   * already a local projection of the checklist, so unchecking a whole volume
   * removes its conflicts from the next graph request.
   */
  const includedPositions = useMemo(
    () =>
      preview
        ? preview.entries.filter((entry) => entry.adopted).map((entry) => entry.cbl_position)
        : [],
    [preview],
  )
  const graphQuery = useQuery({
    queryKey: queryKeys.readingGraph.preview(
      selectedSource?.id ?? 0,
      includedPositions,
      overlapChoices,
    ),
    queryFn: () => {
      if (!selectedSource) throw new Error('Choose a CBL source first.')
      return readingGraphApi.preview(
        selectedSource.id,
        buildReadingGraphRequest(includedPositions, graphPreviewRef.current, overlapChoices),
      )
    },
    enabled: selectedSource !== null && preview !== null,
    placeholderData: (previous) => previous,
    retry: false,
  })
  const graphServerPreview = graphQuery.data ?? null
  // Keep the latest server preview for the next request's overlap payload.
  // A layout effect runs before React Query's fetch effect, so a new checklist
  // answer never sends an older preview while still avoiding a render-phase
  // side effect.
  useLayoutEffect(() => {
    if (graphQuery.data) graphPreviewRef.current = graphQuery.data
  }, [graphQuery.data])

  /**
   * Keep local answers aligned with the server graph: honour decisions the
   * server has already saved for this reader/list, and drop answers whose
   * conflict no longer exists after a checklist change.
   */
  useEffect(() => {
    const data = graphQuery.data
    if (!data) return
    setOverlapChoices((current) => {
      const existing = new Set(data.overlaps.map((overlap) => overlap.overlap_id))
      const next: ReadingGraphChoices = {}
      let changed = false
      for (const [overlapId, choice] of Object.entries(current)) {
        if (existing.has(overlapId)) next[overlapId] = choice
        else changed = true
      }
      for (const overlap of data.overlaps) {
        if (!(overlap.overlap_id in next) && overlap.selected_choice !== null) {
          next[overlap.overlap_id] = overlap.selected_choice
          changed = true
        }
      }
      return changed ? next : current
    })
  }, [graphQuery.data])

  const graph = useMemo(
    () => (graphServerPreview ? withLocalChoices(graphServerPreview, overlapChoices) : null),
    [graphServerPreview, overlapChoices],
  )
  const pendingOverlaps = unresolvedOverlaps(graph, overlapChoices)
  const graphLoading =
    selectedSource !== null && preview !== null && (graphQuery.isPending || graphQuery.isFetching) && !graphQuery.isError
  const graphUnavailable = selectedSource !== null && preview !== null && graphQuery.isError
  const graphCycleErrors = graph?.cycle_errors ?? []
  const pendingOverlapNames = pendingOverlaps
    .map((overlap) => readingGraphSeriesLabel(overlap.waiting_series))
    .join(', ')
  const catalogError = browseQuery.isError ? catalogErrorState(browseQuery.error) : null
  const commitError = staleReview
    ? 'This source changed after you reviewed it. Refresh the preview before adding it.'
    : ambiguousCommit
      ? 'ComicPile did not confirm the new plan in time. Check Reading Plans before adding again.'
      : commitMutation.error &&
          commitSourceId === deepLinkedListId &&
          !isAmbiguousNetworkFailure(commitMutation.error)
        ? errorMessage(commitMutation.error, 'Unable to complete the CBL workflow.')
        : null
  const previewError = previewQuery.error
    ? errorMessage(previewQuery.error, 'Unable to load this CBL source.')
    : null

  /** Move the browser to one folder/search/page position without a preview. */
  const applyBrowseState = (next: {
    folder: string
    query: string
    page: number
    list?: number | null
  }) => {
    const params = new URLSearchParams()
    if (next.folder) params.set('folder', next.folder)
    if (next.query) params.set('q', next.query)
    if (next.page > 1) params.set('page', String(next.page))
    if (next.list) params.set('list', String(next.list))
    setSearchParams(params)
  }

  /** Clear preview-only decisions when the selected source changes. */
  const resetSelectionState = () => {
    setCustomizing(false)
    setConfirmOpen(false)
    setSeriesDecisions({})
    setEntryDecisions({})
    setExpandedGroups({})
    setStaleReview(false)
    setAmbiguousCommit(false)
    setOverlapChoices({})
    setGraphDialogOpen(false)
    setGraphDialogContinuesAdd(false)
    // Only a settled mutation is safe to discard; an in-flight commit stays
    // tracked so no second Add can start while the write is still running.
    if (!commitMutation.isPending) commitMutation.reset()
  }

  const search = (event?: FormEvent) => {
    event?.preventDefault()
    if (isCommitting) return
    resetSelectionState()
    applyBrowseState({ folder, query: queryDraft.trim(), page: 1 })
  }

  const clearSearch = () => {
    if (isCommitting) return
    setQueryDraft('')
    resetSelectionState()
    applyBrowseState({ folder, query: '', page: 1 })
  }

  const openFolder = (path: string) => {
    if (isCommitting) return
    resetSelectionState()
    applyBrowseState({ folder: path, query: '', page: 1 })
  }

  const openPage = (nextPage: number) => {
    if (isCommitting) return
    applyBrowseState({ folder, query: submittedQuery, page: nextPage })
  }

  const openSource = (source: CBLSourceListDiscoveryItem) => {
    if (isCommitting) return
    resetSelectionState()
    applyBrowseState({ folder, query: submittedQuery, page, list: source.id })
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

  /**
   * Record one series-level answer.
   *
   * The answer is scoped to the server's exact volume pair, so it never relaxes
   * another series or a same-titled run. The next graph preview recomputes
   * every blocker from the same evaluator instead of a local guess.
   */
  const chooseOverlap = (overlapId: string, choice: ReadingGraphOverlapChoiceId) => {
    if (isCommitting) return
    setOverlapChoices((current) => ({ ...current, [overlapId]: choice }))
    commitMutation.reset()
    setAmbiguousCommit(false)
  }

  const reviewOverlaps = () => {
    if (isCommitting) return
    setGraphDialogContinuesAdd(false)
    setGraphDialogOpen(true)
  }

  const finishOverlapDialog = () => {
    const continuesAdd = graphDialogContinuesAdd
    setGraphDialogOpen(false)
    setGraphDialogContinuesAdd(false)
    if (continuesAdd && unresolvedOverlaps(graph, overlapChoices).length === 0 && graphCycleErrors.length === 0) {
      setConfirmOpen(true)
    }
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
          : graphCycleErrors.length > 0
            ? 'Resolve the reading-order loop before adding this source.'
            : graphLoading
              ? 'Checking the reading graph…'
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

  const firstShown =
    browsePage && browsePage.items.length > 0
      ? (browsePage.page - 1) * browsePage.page_size + 1
      : 0
  const lastShown = browsePage
    ? (browsePage.page - 1) * browsePage.page_size + browsePage.items.length
    : 0

  const openConfirm = () => {
    if (!selectedSource || !preview || commitBlocked) return
    if (pendingOverlaps.length > 0) {
      setGraphDialogContinuesAdd(true)
      setGraphDialogOpen(true)
      return
    }
    setConfirmOpen(true)
  }

  const confirmCommit = () => {
    if (!selectedSource || !preview || isCommitting || graphCycleErrors.length > 0 || graphLoading || pendingOverlaps.length > 0) return
    setConfirmOpen(false)
    setCommitSourceId(selectedSource.id)
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
          value={queryDraft}
          onChange={(event) => setQueryDraft(event.target.value)}
          placeholder="Search source lists"
          maxLength={200}
          disabled={isCommitting}
          className="min-h-11 flex-1 rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-3 text-[var(--theme-text-primary)] disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={isCommitting}
          className="min-h-11 rounded-xl bg-[var(--theme-continuity-accent)] px-4 text-sm font-black text-black disabled:opacity-50"
        >
          Search
        </button>
      </form>

      {deepLinkedListId !== null ? (
        <div className="space-y-4">
          <CblSourceDetailPanel
            listId={deepLinkedListId}
            {...(isObject(location.state) && isString((location.state as Record<string, unknown>).from)
              ? {}
              : {
                  backHref: browseHref(folder, submittedQuery, page),
                  // `CblSourceDetailPanel` already prefixes "Back to", so the
                  // label is the destination only — at the root too.
                  backLabel: 'results',
                })}
          />

          {previewError && (
            <p role="alert" className="text-sm text-[var(--theme-danger)]">
              {previewError}
            </p>
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
            <p className="text-xs text-[var(--theme-warning)]">
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

          {graphUnavailable && (
            <p role="status" className="text-xs text-[var(--theme-warning)]">
              ComicPile could not load the reading graph, so it cannot check overlapping series
              right now. You can still add this source.{' '}
              <button
                type="button"
                onClick={() => void graphQuery.refetch()}
                className="font-bold underline underline-offset-2"
              >
                Retry graph
              </button>
            </p>
          )}

          {graph && hasGenuineOverlap(graph) && (
            <ReadingGraphSummary
              preview={graph}
              choices={overlapChoices}
              onReview={reviewOverlaps}
              disabled={isCommitting}
              busy={graphQuery.isFetching}
            />
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
              {!commitBlockedReason && pendingOverlaps.length > 0 && (
                <p className="max-w-xs text-xs text-[var(--theme-warning)]">
                  {pendingOverlaps.length === 1
                    ? `Decide how ${pendingOverlapNames} should continue before adding this source.`
                    : `Decide how ${pendingOverlaps.length} overlapping series should continue before adding this source.`}
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
                                      <span className="mt-1 block text-xs text-[var(--theme-warning)]">
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
        </div>
      ) : (
        <>
          {submittedQuery && (
            <div className="flex flex-wrap items-center gap-2 text-xs text-[var(--theme-text-muted)]">
              <span>Searching every shared CBL for “{submittedQuery}”.</span>
              <button
                type="button"
                onClick={clearSearch}
                disabled={isCommitting}
                className="min-h-9 rounded-lg border border-[var(--theme-border)] px-2 font-bold text-[var(--theme-text-primary)] hover:bg-white/5 disabled:opacity-50"
              >
                Clear search
              </button>
            </div>
          )}

          {catalogError && (
            <div role="alert" className="space-y-2 text-sm text-[var(--theme-error)]">
              <p>{catalogError.message}</p>
              <button
                type="button"
                onClick={() => {
                  if (catalogError.recover === 'browse-root') {
                    resetSelectionState()
                    applyBrowseState({ folder: '', query: '', page: 1 })
                    return
                  }
                  void browseQuery.refetch()
                }}
                className="min-h-9 rounded-lg border border-[var(--theme-border)] px-3 text-xs font-bold text-[var(--theme-text-primary)] hover:bg-white/5"
              >
                {catalogError.recover === 'browse-root' ? 'Browse all CBLs' : 'Try again'}
              </button>
            </div>
          )}

          {browseQuery.isPending && (
            <p role="status" className="text-sm text-[var(--theme-text-muted)]">
              Loading the shared CBL catalog…
            </p>
          )}

          {browsePage && !catalogError && (
            <div className="space-y-4" data-testid="cbl-browse-results">
              {browsePage.scope === 'folder' && (
                <nav aria-label="CBL folder path" className="flex flex-wrap items-center gap-1 text-xs">
                  {browsePage.breadcrumbs.map((crumb, index) => {
                    const isCurrent = index === browsePage.breadcrumbs.length - 1
                    return (
                      <Fragment key={crumb.path || 'root'}>
                        {index > 0 && (
                          <span aria-hidden="true" className="text-[var(--theme-text-dim)]">
                            /
                          </span>
                        )}
                        <button
                          type="button"
                          disabled={isCommitting}
                          onClick={() => openFolder(crumb.path)}
                          aria-current={isCurrent ? 'page' : undefined}
                          className={`min-h-9 rounded-lg px-2 font-bold disabled:opacity-50 ${
                            isCurrent
                              ? 'text-[var(--theme-text-primary)]'
                              : 'text-[var(--theme-continuity-accent)] hover:bg-white/5'
                          }`}
                        >
                          {crumb.name}
                        </button>
                      </Fragment>
                    )
                  })}
                </nav>
              )}

              {browsePage.folders.length > 0 && (
                <ul className="grid gap-2 sm:grid-cols-2" aria-label="CBL folders">
                  {browsePage.folders.map((child) => (
                    <li key={child.path}>
                      <button
                        type="button"
                        disabled={isCommitting || browseQuery.isPlaceholderData}
                        onClick={() => openFolder(child.path)}
                        className="w-full rounded-xl border border-[var(--theme-border)] p-3 text-left hover:bg-white/5 disabled:opacity-50"
                      >
                        <span className="block text-sm font-bold text-[var(--theme-text-primary)]">
                          {child.name}
                        </span>
                        <span className="mt-1 block text-xs text-[var(--theme-text-dim)]">
                          {sourceCountLabel(child.total_list_count)}
                          {child.direct_list_count !== child.total_list_count
                            ? ` · ${sourceCountLabel(child.direct_list_count)} here`
                            : ''}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}

              {browsePage.items.length > 0 && (
                <ul className="grid gap-2" aria-label="Source candidates">
                  {browsePage.items.map((source) => {
                    const publicRepo = displayCblRepository(source.source_repository)
                    const title =
                      displayCblSourceTitle(source.name, source.source_path) ??
                      FALLBACK_SOURCE_TITLE
                    const meta = [
                      publicRepo,
                      source.declared_issue_count !== null
                        ? `${source.declared_issue_count} issues`
                        : null,
                    ].filter(Boolean)
                    return (
                      <li key={source.id}>
                        <button
                          type="button"
                          onClick={() => openSource(source)}
                          disabled={isCommitting || browseQuery.isPlaceholderData}
                          className="w-full rounded-xl border border-[var(--theme-border)] p-3 text-left hover:bg-white/5 disabled:opacity-50"
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
                      </li>
                    )
                  })}
                </ul>
              )}

              {browsePage.items.length === 0 && browsePage.folders.length === 0 && (
                <p className="text-sm text-[var(--theme-text-muted)]">
                  {browsePage.scope === 'search'
                    ? 'No matching source lists found.'
                    : browsePage.folder
                      ? 'No CBL sources in this folder.'
                      : 'No shared CBL sources are available yet.'}
                </p>
              )}

              {browsePage.items.length === 0 && browsePage.total > 0 && (
                <p className="text-sm text-[var(--theme-text-muted)]">
                  No sources on page {browsePage.page} of {Math.max(browsePage.total_pages, 1)}.
                </p>
              )}

              {browsePage.total > 0 && (
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p role="status" className="text-xs text-[var(--theme-text-muted)]">
                    Showing {firstShown}–{lastShown} of {sourceCountLabel(browsePage.total)}
                  </p>
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => openPage(page - 1)}
                      disabled={!browsePage.has_previous || isCommitting || browseQuery.isPlaceholderData}
                      className="min-h-9 rounded-lg border border-[var(--theme-border)] px-3 text-xs font-bold text-[var(--theme-text-primary)] hover:bg-white/5 disabled:opacity-50"
                    >
                      Previous page
                    </button>
                    <span className="text-xs text-[var(--theme-text-muted)]">
                      Page {browsePage.page} of {Math.max(browsePage.total_pages, 1)}
                    </span>
                    <button
                      type="button"
                      onClick={() => openPage(page + 1)}
                      disabled={!browsePage.has_next || isCommitting || browseQuery.isPlaceholderData}
                      className="min-h-9 rounded-lg border border-[var(--theme-border)] px-3 text-xs font-bold text-[var(--theme-text-primary)] hover:bg-white/5 disabled:opacity-50"
                    >
                      Next page
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}
        </>
      )}

      {graph && (
        <ReadingGraphOverlapDialog
          isOpen={graphDialogOpen}
          preview={graph}
          choices={overlapChoices}
          onChoose={chooseOverlap}
          onClose={() => {
            setGraphDialogOpen(false)
            setGraphDialogContinuesAdd(false)
          }}
          onDone={finishOverlapDialog}
          busy={graphQuery.isFetching}
        />
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

    </section>
  )
}
