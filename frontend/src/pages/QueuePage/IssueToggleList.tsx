import {
  useState,
  useEffect,
  useCallback,
  useMemo,
  useId,
  useRef,
  forwardRef,
  useImperativeHandle,
} from 'react'
import type { DragEvent } from 'react'
import type { Issue, IssueDependenciesResponse, IssueListResponse } from '../../types'
import { issuesApi } from '../../services/api-issues'
import type { IssueCreateOptions, IssueEditPreviewResponse, IssueListParams } from '../../services/api-issues'
import { undoApi as defaultUndoApi } from '../../services/api-undo'
import { issueDependenciesApi } from '../../services/api-dependencies'
import type { ThreadIssueDependenciesResponse } from '../../services/api-dependencies'
import { getApiErrorDetail } from '../../utils/apiError'
import { validateIssueRangeForStaging } from '../../utils/issueParser'
import { isWindowDefined, isFunction } from '../../utils/runtimeChecks'
import Tooltip from '../../components/Tooltip'
import Modal from '../../components/Modal'
import DeleteIssueDialog from './DeleteIssueDialog'
import { PostCreateUndoBar } from './IssueEditPreviewParts'
import { IssueCreatePreviewModal } from './IssueCreatePreviewModal'
import { IssuePreviewErrorModal } from './IssuePreviewErrorModal'
import { IssueStructurePreviewModal } from './IssueStructurePreviewModal'
import { useIssueStructurePreview } from './useIssueStructurePreview'
import type { StructuralEdit } from './useIssueStructurePreview'
import type { IssueToggleListApi, IssueToggleListDependenciesApi, IssueToggleListHandle } from './IssueToggleList.api'
export type { IssueToggleListApi, IssueToggleListDependenciesApi, IssueToggleListHandle } from './IssueToggleList.api'
import CompactIssueCardTrigger from '../../components/CompactIssueCardTrigger'
import { useIssueCards, indexIssueCards } from '../../hooks/useIssueCards'
import type { IssueReadRateResponse } from '../../services/issueCardsApi'
import { getDependencyTooltip } from '../../utils/dependencyHelpers'
import {
  reorderIssuesForDrop,
  moveIssueByStep,
  normalizeIssueOrder,
  applyIssueMutation,
  applyIssueMutations,
  getPendingIssueIds,
  getPendingCreates,
} from './issueUtils'
import type { IssueMutation, QueuedIssueMutation } from './types'

/**
 * A reversible edit captured while a deferred Edit Series draft is saved.
 * Creates reuse the #4026/#4027 snapshot; reorder records the exact pre-edit
 * ID order and reverses it with the same ownership-checked issue-order write.
 * Actions are applied newest-first so a create + reorder batch unwinds cleanly.
 */
type UndoAction =
  | { kind: 'snapshot'; sessionId: number; snapshotId: number }
  | { kind: 'reorder'; issueIds: number[] }

type DraftReorder = {
  nextIssues: Issue[]
  announcement?: string
  focusTarget?: { issueId: number; direction: 'up' | 'down' }
}

export const IssueToggleList = forwardRef<IssueToggleListHandle, {
  threadId: number
  onOpenDependencies?: () => void
  onIssueChanged?: () => void
  onLoad?: () => void
  /**
   * Reports whether this list still has draft mutations awaiting Save.
   * Edit Series uses it to warn before discarding unsaved issue changes.
   */
  onPendingMutationsChange?: (hasPending: boolean) => void
  /** Injectable issue API; defaults to the production issuesApi. */
  issuesApi?: IssueToggleListApi
  /** Injectable dependency API; defaults to the production issueDependenciesApi. */
  dependenciesApi?: IssueToggleListDependenciesApi
  /** Injectable undo API; defaults to the shared #4026/#4027 undo service. */
  undoApi?: {
    undo: (sessionId: number | string, snapshotId: number | string) => Promise<void>
  }
  /**
   * When true, mutations queue locally without hitting the server until
   * flush() is called. Closing without flushing discards the draft.
   * Defaults to false (immediate mode, for ThreadDetailView).
   */
  deferred?: boolean
}>(function IssueToggleList({
  threadId,
  onOpenDependencies,
  onIssueChanged,
  onLoad,
  onPendingMutationsChange,
  issuesApi: issuesService = issuesApi,
  dependenciesApi = issueDependenciesApi,
  undoApi: undoService = defaultUndoApi,
  deferred = false,
}, ref) {
  const [issues, setIssues] = useState<Issue[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [addRange, setAddRange] = useState('')
  const [isAdding, setIsAdding] = useState(false)
  const [addError, setAddError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [reorderAnnouncement, setReorderAnnouncement] = useState('')
  const [toggling, setToggling] = useState<Set<number>>(new Set())
  const [deleting, setDeleting] = useState<Set<number>>(new Set())
  const [draggedIssueId, setDraggedIssueId] = useState<number | null>(null)
  const [dragOverIssueId, setDragOverIssueId] = useState<number | null>(null)
  const [dependencies, setDependencies] = useState<Record<number, IssueDependenciesResponse>>({})
  const [selectedDepsIssue, setSelectedDepsIssue] = useState<Issue | null>(null)
  const [isExpanded, setIsExpanded] = useState(false)
  const [isReorderMode, setIsReorderMode] = useState(false)
  const [deleteDialogIssue, setDeleteDialogIssue] = useState<Issue | null>(null)
  const [previewState, setPreviewState] = useState<{
    range: string
    response: IssueEditPreviewResponse
    selectedStrategy: 'safe_default' | 'numeric_resort'
  } | null>(null)
  const [isPreviewing, setIsPreviewing] = useState(false)
  /** Preview fetch failure, surfaced in a retryable modal (#4654). */
  const [previewError, setPreviewError] = useState<string | null>(null)
  /** Numbers the reader explicitly accepted as aliases, not duplicates (#4654). */
  const [acceptedAliasNumbers, setAcceptedAliasNumbers] = useState<string[]>([])
  /**
   * Undo points from committed creates and reorders (#4654, #5852). The array
   * mirrors the ref so parents reading hasUndoPoint() synchronously after
   * flush() see the same truth as the rendered Undo affordance.
   */
  const [undoActions, setUndoActions] = useState<UndoAction[]>([])
  const undoActionsRef = useRef<UndoAction[]>([])
  const [isUndoing, setIsUndoing] = useState(false)
  /**
   * A reorder is shown immediately as a local pending change (#5852). The
   * server projection is still fetched and confirmed before the mutation is
   * queued, so a failed preview never silently commits a structural edit.
   */
  const [draftReorder, setDraftReorder] = useState<DraftReorder | null>(null)
  const [structurePreviewError, setStructurePreviewError] = useState<string | null>(null)
  const structuralEditRef = useRef<StructuralEdit | null>(null)
  const baseIssuesRef = useRef<Issue[]>([])
  const pendingMutationsRef = useRef<IssueMutation[]>([])
  const isProcessingMutationsRef = useRef(false)
  const nextMutationIdRef = useRef(1)
  const onPendingMutationsChangeRef = useRef(onPendingMutationsChange)
  useEffect(() => {
    onPendingMutationsChangeRef.current = onPendingMutationsChange
  })
  /**
   * A structural edit is staged as soon as the reader confirms the destructive
   * dialog (delete) or starts a draft reorder — before its before/after preview
   * resolves and even if that preview fails. Edit Series must call that draft
   * dirty so closing asks whether to discard it (MQA-QUEUE-008 / #5864). The
   * queued-mutation count alone misses this window because #4654 defers the
   * actual enqueue until the preview is confirmed.
   */
  const hasStagedStructuralRef = useRef(false)
  const notifyPendingMutations = useCallback(() => {
    onPendingMutationsChangeRef.current?.(
      pendingMutationsRef.current.length > 0 || hasStagedStructuralRef.current
    )
  }, [])
  const setStagedStructural = useCallback((staged: boolean) => {
    if (hasStagedStructuralRef.current === staged) return
    hasStagedStructuralRef.current = staged
    notifyPendingMutations()
  }, [notifyPendingMutations])
  const recordUndoAction = useCallback((action: UndoAction) => {
    // handleUndoEdit replays this array, so keep it strictly newest-first:
    // every committed action is prepended, never appended (#5852).
    const next = [action, ...undoActionsRef.current]
    undoActionsRef.current = next
    setUndoActions(next)
  }, [])
  const displayIssues = draftReorder?.nextIssues ?? issues
  const hasStructuralPreview = Boolean(issuesService.previewReorder)
  const pendingReorderEffects = useMemo(() => {
    if (!draftReorder) return []
    const originalPositions = new Map(issues.map((issue, index) => [issue.id, index + 1]))
    return draftReorder.nextIssues.flatMap((issue, index) => {
      const before = originalPositions.get(issue.id)
      return before !== undefined && before !== index + 1
        ? [{ id: issue.id, issueNumber: issue.issue_number, before, after: index + 1 }]
        : []
    })
  }, [draftReorder, issues])
  const loadGenerationRef = useRef(0)
  const totalCountRef = useRef(0)
  const fullyLoadedRef = useRef(false)
  const addInputId = useId()
  const addValidationErrorId = useId()
  const addServerErrorId = useId()

  /**
   * Client-side guard for the Add box (#3586). The backend parser accepts any
   * literal identifier, so without this guard arbitrary text ("abc"), a
   * negative number ("-3"), or a zero-width character becomes a pending issue
   * chip that is one Save away from becoming a phantom record.
   */
  const addRangeValidation = useMemo(
    () => validateIssueRangeForStaging(addRange),
    [addRange],
  )
  const addValidationError = addRangeValidation.error
  const isAddRangeValid = addRangeValidation.valid
  const addErrorDescription = [
    addValidationError ? addValidationErrorId : null,
    addError ? addServerErrorId : null,
  ].filter((id): id is string => id !== null).join(' ') || undefined

  const getNextUnreadIssueId = useCallback(() => {
    return displayIssues.find((issue) => issue.status === 'unread')?.id ?? null
  }, [displayIssues])

  const getVisibilityWindow = useCallback((issueList: Issue[], nextUnreadId: number | null) => {
    if (!nextUnreadId) {
      return { startIndex: issueList.length - 3, endIndex: issueList.length }
    }

    const nextUnreadIndex = issueList.findIndex((issue) => issue.id === nextUnreadId)
    const readBeforeCount = 3
    const unreadAfterCount = 3
    const startIndex = Math.max(0, nextUnreadIndex - readBeforeCount)
    const endIndex = Math.min(issueList.length, nextUnreadIndex + unreadAfterCount + 1)

    return { startIndex, endIndex }
  }, [])

  const getVisibleIssues = useCallback(() => {
    if (isExpanded || displayIssues.length <= 5) {
      return displayIssues
    }

    const nextUnreadId = getNextUnreadIssueId()
    const { startIndex, endIndex } = getVisibilityWindow(displayIssues, nextUnreadId)

    return displayIssues.slice(startIndex, endIndex)
  }, [displayIssues, isExpanded, getNextUnreadIssueId, getVisibilityWindow])

  // Visible issue pills share one bounded projection; expanding the reorder
  // view expands that batch. No per-row metadata requests.
  const issueCardsQuery = useIssueCards(
    (isReorderMode ? displayIssues : getVisibleIssues()).map((issue) => issue.id),
    { enabled: !isLoading && !loadError },
  )
  const cardsByIssue = indexIssueCards(issueCardsQuery.data)

  const [pendingCreates, setPendingCreates] = useState<string[]>([])

  const syncOptimisticIssues = useCallback((baseIssues: Issue[], pendingMutations: IssueMutation[]) => {
    setIssues(applyIssueMutations(baseIssues, pendingMutations))
    setToggling(getPendingIssueIds(pendingMutations, 'toggle'))
    setDeleting(getPendingIssueIds(pendingMutations, 'delete'))
    setPendingCreates(getPendingCreates(pendingMutations))
  }, [])

  // A direct issue read/rating is independent of the Edit Series draft.
  // Keep pending staged edits intact atop the newly confirmed baseline.
  const onDirectIssueMutated = useCallback((response: IssueReadRateResponse) => {
    baseIssuesRef.current = baseIssuesRef.current.map((issue) =>
      issue.id === response.issue.issue_id
        ? {
            ...issue,
            status: response.issue.status === 'read' ? 'read' : 'unread',
            read_at: response.issue.status === 'read' ? (response.issue.read_at ?? issue.read_at) : null,
          }
        : issue,
    )
    syncOptimisticIssues(baseIssuesRef.current, pendingMutationsRef.current)
    onIssueChanged?.()
  }, [onIssueChanged, syncOptimisticIssues])

  const fetchAllIssues = useCallback(async (): Promise<Issue[]> => {
    const allIssues: Issue[] = []
    const seenPageTokens = new Set<string>()
    let nextPageToken: string | null = null
    let totalCount = 0

    while (true) {
      const params: IssueListParams = { page_size: 100 }
      if (nextPageToken) {
        params.page_token = nextPageToken
      }
      const data = await issuesService.list(threadId, params)
      // The server's `total_count` is the authority for the completeness
      // check (#3764). Keep the largest count any page reported: a count that
      // grows while the pages are being fetched would otherwise let a
      // truncated list pass the check against a stale, smaller total.
      if (data.total_count > totalCount) {
        totalCount = data.total_count
      }
      allIssues.push(...data.issues)

      if (!data.next_page_token || seenPageTokens.has(data.next_page_token)) {
        totalCountRef.current = totalCount
        return allIssues
      }

      seenPageTokens.add(data.next_page_token)
      nextPageToken = data.next_page_token
    }
  }, [issuesService, threadId])

  const fetchDependencies = useCallback(async (): Promise<Record<number, IssueDependenciesResponse>> => {
    try {
      const response = await dependenciesApi.listForThread(threadId)
      const depsMap: Record<number, IssueDependenciesResponse> = {}

      for (const issueDependencies of response.issues) {
        if (
          issueDependencies.incoming.length > 0
          || issueDependencies.outgoing.length > 0
        ) {
          depsMap[issueDependencies.issue_id] = issueDependencies
        }
      }

      return depsMap
    } catch (error) {
      console.error(`Failed to load dependencies for thread ${threadId}:`, error)
      return {}
    }
  }, [dependenciesApi, threadId])

  const focusMoveControl = useCallback((issueId: number, direction: 'up' | 'down') => {
    const focusTarget = () => {
      document
        .querySelector<HTMLButtonElement>(`[data-move-control="${direction}-${issueId}"]`)
        ?.focus()
    }

    if (isWindowDefined() && isFunction(window.requestAnimationFrame)) {
      window.requestAnimationFrame(focusTarget)
      return
    }

    setTimeout(focusTarget, 0)
  }, [])

  const runIssueMutation = useCallback(async (mutation: IssueMutation) => {
    switch (mutation.type) {
      case 'toggle':
        if (mutation.nextStatus === 'read') {
          await issuesService.markRead(mutation.issueId)
        } else {
          await issuesService.markUnread(mutation.issueId)
        }
        return
      case 'delete':
        await issuesService.delete(mutation.issueId)
        return
      case 'reorder': {
        // Capture the exact pre-edit ID order while baseIssuesRef is still the
        // uncommitted server snapshot (#5852). Reversing through the same
        // ownership-checked issue-order write preserves issue IDs, dependencies,
        // list memberships, ratings, read facts and Queue position.
        const previousIssueIds = baseIssuesRef.current.map((issue) => issue.id)
        await issuesService.reorder(threadId, normalizeIssueOrder(baseIssuesRef.current, mutation.issueIds))
        recordUndoAction({ kind: 'reorder', issueIds: previousIssueIds })
        return
      }
      case 'create': {
        const options: IssueCreateOptions = {}
        if (mutation.strategy) {
          options.strategy = mutation.strategy
        }
        if (mutation.expectedIssueIds && mutation.expectedIssueIds.length > 0) {
          options.expected_issue_ids = mutation.expectedIssueIds
        }
        if (mutation.acceptedAliasNumbers && mutation.acceptedAliasNumbers.length > 0) {
          options.accepted_alias_numbers = mutation.acceptedAliasNumbers
        }
        const response = await issuesService.create(threadId, mutation.issueRange, options)
        if (response.undo_session_id != null && response.undo_snapshot_id != null) {
          recordUndoAction({
            kind: 'snapshot',
            sessionId: response.undo_session_id,
            snapshotId: response.undo_snapshot_id,
          })
        }
        return
      }
    }
  }, [issuesService, recordUndoAction, threadId])

  const processIssueMutations = useCallback(async () => {
    if (isProcessingMutationsRef.current) {
      return
    }

    isProcessingMutationsRef.current = true
    let hadSuccess = false

    try {
      while (pendingMutationsRef.current.length > 0) {
        const currentMutation = pendingMutationsRef.current[0]
        try {
          await runIssueMutation(currentMutation)
          if (currentMutation.type === 'create') {
            // A create changes which issues exist, and the server places new
            // issues at their natural position rather than appending them.
            // Re-read the thread so the base list matches server order before
            // any later queued mutation (notably reorder) is derived from it.
            if (!fullyLoadedRef.current) {
              throw new Error('Issues are not fully loaded; save aborted.')
            }
            // Once create succeeds the old snapshot lacks the new issue.
            // Keep Save blocked even if both refresh requests reject.
            fullyLoadedRef.current = false
            const refreshed = await fetchAllIssues()
            const expectedTotal = totalCountRef.current
            if (expectedTotal > 0 && refreshed.length < expectedTotal) {
              // An incomplete post-create refresh must not leave the list
              // marked fully loaded: the next Save would otherwise pass the
              // load guard and flush a queued reorder from a base that still
              // lacks the new issue (#4113).
              fullyLoadedRef.current = false
              throw new Error('Could not load all issues; save aborted.')
            }
            baseIssuesRef.current = refreshed
            fullyLoadedRef.current = true
          } else {
            baseIssuesRef.current = applyIssueMutation(baseIssuesRef.current, currentMutation)
          }
          hadSuccess = true
        } catch (err: unknown) {
          // A failed mutation stops the queue and is reported to the caller.
          // The rejected edit rolls back; later mutations stay queued so the
          // reader's next Save retries the remaining batch. A fresh preview
          // can always re-add the rejected edit (#4654).
          //
          // The base list is resynchronized with the server first. When that
          // resynchronization is itself incomplete, later mutations would be
          // derived from a truncated issue list, so the queue must stop
          // (#3764).
          try {
            const refreshed = await fetchAllIssues()
            const expectedTotal = totalCountRef.current
            if (expectedTotal > 0 && refreshed.length < expectedTotal) {
              throw new Error('Synchronization incomplete; save aborted.')
            }
            baseIssuesRef.current = refreshed
            // A complete catch-path resync restores trust in the base list so
            // a later Save can flush remaining mutations (including reorder)
            // without forcing an extra manual reload (#4113).
            fullyLoadedRef.current = true
          } catch (refreshErr) {
            // The failed mutation is the root cause; the failed resync is a
            // secondary failure. Report the root cause to the reader and keep
            // both failures in the log, so the reason the save stopped is
            // never lost behind the resync error (#3764).
            //
            // When a post-create refresh already cleared the loaded flag, the
            // base list is missing the new issue. Surface Retry so a later
            // Save cannot flush a stale reorder that the server would reject
            // and drop from the queue (#4113). If the loaded flag is still
            // true, the last complete snapshot remains trusted — do not hide
            // the list or permanently block Save behind Retry.
            if (!fullyLoadedRef.current) {
              setLoadError('Could not load all issues. Please retry.')
            }
            console.error(
              '[IssueToggleList] Mutation failed and the follow-up resync also failed:',
              { mutationError: err, resyncError: refreshErr },
            )
            setActionError(getApiErrorDetail(err))
            throw new Error(
              `${getApiErrorDetail(err)} (issue list resync failed: ${getApiErrorDetail(refreshErr)})`,
            )
          }
          setActionError(getApiErrorDetail(err))
          throw err
        } finally {
          pendingMutationsRef.current = pendingMutationsRef.current.filter(
            (mutation) => mutation.id !== currentMutation.id
          )
          syncOptimisticIssues(baseIssuesRef.current, pendingMutationsRef.current)
          notifyPendingMutations()
        }
      }
    } finally {
      isProcessingMutationsRef.current = false
      if (hadSuccess) {
        onIssueChanged?.()
      }
    }
  }, [fetchAllIssues, runIssueMutation, syncOptimisticIssues, onIssueChanged, notifyPendingMutations])

  const enqueueIssueMutation = useCallback((mutation: QueuedIssueMutation) => {
    // SAFETY: spreading the queued mutation and adding the sequential id satisfies the IssueMutation contract.
    const queuedMutation = {
      ...mutation,
      id: nextMutationIdRef.current++,
    } as IssueMutation

    pendingMutationsRef.current = [...pendingMutationsRef.current, queuedMutation]
    syncOptimisticIssues(baseIssuesRef.current, pendingMutationsRef.current)
    notifyPendingMutations()
    if (!deferred) {
      // Immediate mode has no caller awaiting the queue, so a failed flush
      // must not escape as an unhandled rejection. The inline action error
      // already reports the failure, and the mutations that were not applied
      // stay queued for the next attempt.
      void processIssueMutations().catch(() => undefined)
    }
  }, [processIssueMutations, syncOptimisticIssues, deferred, notifyPendingMutations])

  // Imperative handle for deferred mode: flush on save, discard on unmount.
  useImperativeHandle(ref, () => ({
    flush: async () => {
      if (!fullyLoadedRef.current) {
        // Report why the save is refused instead of failing silently, so the
        // reader can see that the issue list must load completely first
        // (#3764).
        const message = 'Issues are not fully loaded; save aborted.'
        setActionError(message)
        throw new Error(message)
      }
      await processIssueMutations()
    } ,
    hasPendingMutations: () => pendingMutationsRef.current.length > 0,
    hasUndoPoint: () => undoActionsRef.current.length > 0,
  }), [processIssueMutations, setActionError])

  const enqueueIssueReorder = useCallback((
    nextIssues: Issue[],
    options?: {
      announcement?: string
      focusTarget?: { issueId: number; direction: 'up' | 'down' }
    }
  ) => {
    const nextIssueIds = nextIssues.map((issue) => issue.id)
    const currentIssueIds = issues.map((issue) => issue.id)
    const orderDidChange = nextIssueIds.some((issueId, index) => issueId !== currentIssueIds[index])

    if (!orderDidChange) {
      return false
    }

    setActionError(null)
    if (options?.announcement) {
      setReorderAnnouncement(options.announcement)
    }
    // The queued mutation is applied to `issues` synchronously, so the draft
    // projection must be released in the same commit (#5852). Keeping it would
    // pin the displayed order to a stale snapshot on the next move.
    setDraftReorder(null)
    enqueueIssueMutation({
      type: 'reorder',
      issueIds: nextIssueIds,
    })
    if (options?.focusTarget) {
      focusMoveControl(options.focusTarget.issueId, options.focusTarget.direction)
    }
    return true
  }, [enqueueIssueMutation, focusMoveControl, issues])

  // Held in a ref so loadIssues keeps a stable identity: the load effect keys
  // off loadIssues, so depending on onLoad directly would re-trigger a fetch
  // whenever a caller passed an unmemoized callback.
  const onLoadRef = useRef(onLoad)
  useEffect(() => {
    onLoadRef.current = onLoad
  }, [onLoad])

  const loadIssues = useCallback(async () => {
    const loadGeneration = ++loadGenerationRef.current
    setIsLoading(true)
    setLoadError(null)

    try {
      const nextIssues = await fetchAllIssues()
      if (loadGeneration !== loadGenerationRef.current) {
        return
      }

      // Refuse to publish a partial issue set: if the server reports more
      // issues than we actually loaded, keep the dialog in the loading/error
      // state instead of silently operating on a truncated list (#3764).
      const expectedTotal = totalCountRef.current
      if (expectedTotal > 0 && nextIssues.length < expectedTotal) {
        fullyLoadedRef.current = false
        setLoadError('Could not load all issues. Please retry.')
        return
      }

      fullyLoadedRef.current = true
      baseIssuesRef.current = nextIssues
      syncOptimisticIssues(nextIssues, pendingMutationsRef.current)
      // A complete load supersedes an earlier "not fully loaded" refusal, so
      // the reader is not left with a stale aborted-save message (#3764).
      setActionError(null)

      const nextDependencies = await fetchDependencies()
      if (loadGeneration !== loadGenerationRef.current) {
        return
      }

      setDependencies(nextDependencies)
    } catch (err: unknown) {
      if (loadGeneration !== loadGenerationRef.current) {
        return
      }
      fullyLoadedRef.current = false
      setLoadError(getApiErrorDetail(err))
    } finally {
      if (loadGeneration === loadGenerationRef.current) {
        setIsLoading(false)
        // Only notify the caller if we actually reached a fully loaded state.
        // If we are in a partial-load error state, the caller's Save button
        // stays disabled (showing "Loading issues..."), preventing a partial save.
        if (fullyLoadedRef.current) {
          onLoadRef.current?.()
        }
      }
    }
  }, [fetchAllIssues, fetchDependencies, syncOptimisticIssues])

  useEffect(() => {
    void loadIssues()

    return () => {
      loadGenerationRef.current += 1
    }
  }, [loadIssues])

  function handleToggle(issue: Issue) {
    const newStatus = issue.status === 'read' ? 'unread' : 'read'

    setActionError(null)
    enqueueIssueMutation({
      type: 'toggle',
      issueId: issue.id,
      nextStatus: newStatus,
    })
  }

  async function handleAddIssues() {
    const range = addRange.trim()
    if (!range) {
      return
    }
    // Reject input that is not an issue before it can become a pending chip
    // or reach the server (#3586). The same guard also drives the inline
    // error and the disabled state of the Add button.
    const validation = validateIssueRangeForStaging(range)
    if (!validation.valid) {
      return
    }
    setAddError(null)
    setPreviewError(null)
    if (deferred) {
      setIsPreviewing(true)
      try {
        const response = await issuesService.previewCreate(threadId, range, {
          accepted_alias_numbers: acceptedAliasNumbers,
        })
        setPreviewState({
          range,
          response,
          selectedStrategy: 'safe_default',
        })
      } catch (err: unknown) {
        console.error('[IssueToggleList] Error previewing issues:', err)
        const detail = getApiErrorDetail(err)
        setAddError(detail)
        setPreviewError(detail)
      } finally {
        setIsPreviewing(false)
      }
      return
    }
    setIsAdding(true)
    try {
      await issuesService.create(threadId, range)
      setAddRange('')
      await loadIssues()
    } catch (err: unknown) {
      console.error('[IssueToggleList] Error adding issues:', err)
      setAddError(getApiErrorDetail(err))
    } finally {
      setIsAdding(false)
    }
  }

  function handleConfirmPreview() {
    if (!previewState) return
    const outcome = previewState.selectedStrategy === 'numeric_resort'
      ? previewState.response.numeric_resort_outcome
      : previewState.response.default_outcome
    if (!outcome?.can_commit) return
    enqueueIssueMutation({
      type: 'create',
      issueRange: previewState.range,
      strategy: previewState.selectedStrategy,
      expectedIssueIds: previewState.response.expected_issue_ids,
      acceptedAliasNumbers,
    })
    setAddRange('')
    setPreviewState(null)
    setAcceptedAliasNumbers([])
  }

  function closePreview() {
    setPreviewState(null)
    setAcceptedAliasNumbers([])
  }

  function toggleAliasOffer(number: string) {
    if (!previewState) return
    const nextAccepted = acceptedAliasNumbers.includes(number)
      ? acceptedAliasNumbers.filter((candidate) => candidate !== number)
      : [...acceptedAliasNumbers, number]
    setAcceptedAliasNumbers(nextAccepted)
    setIsPreviewing(true)
    // Accepting an alias requires a fresh preview so the Before/After rows and
    // the exact graph outcome reflect the number no longer being created.
    void issuesService
      .previewCreate(threadId, previewState.range, {
        accepted_alias_numbers: nextAccepted,
      })
      .then((response) => setPreviewState({ ...previewState, response }))
      .catch((err: unknown) => {
        console.error('[IssueToggleList] Error re-previewing aliases:', err)
        setPreviewError(getApiErrorDetail(err))
      })
      .finally(() => setIsPreviewing(false))
  }

  const {
    preview: structurePreview, isPreviewing: isPreviewingStructure,
    request: requestStructuralPreview, cancel: cancelStructurePreview,
    confirm: confirmStructurePreview,
  } = useIssueStructurePreview({
    threadId,
    deferred,
    previewDelete: issuesService.previewDelete,
    previewReorder: issuesService.previewReorder,
    onDelete: (issueId: number) => {
      setActionError(null)
      setStagedStructural(false)
      enqueueIssueMutation({ type: 'delete', issueId })
    },
    onReorder: (nextIssues, options) => {
      if (enqueueIssueReorder(nextIssues, options)) {
        setStagedStructural(false)
      }
    },
    onError: (message: string) => {
      setActionError(message)
      setStructurePreviewError(message)
    },
  })

  /**
   * Show the requested order immediately (so a click is never a silent no-op)
   * while the server still projects the exact constraints before commit.
   * A seam-less caller keeps the historical direct path and needs no draft.
   */
  const requestStructuralEdit = useCallback((edit: StructuralEdit) => {
    structuralEditRef.current = edit
    const hasPreview = edit.type === 'delete'
      ? Boolean(issuesService.previewDelete)
      : hasStructuralPreview
    if (deferred && hasPreview && edit.type === 'reorder') {
      setDraftReorder({
        nextIssues: edit.nextIssues,
        announcement: edit.announcement,
        focusTarget: edit.focusTarget,
      })
      // The proposed order is visible immediately, so the draft is already
      // dirty even though the mutation is queued only after preview confirm.
      setStagedStructural(true)
    }
    setStructurePreviewError(null)
    void requestStructuralPreview(edit)
  }, [deferred, hasStructuralPreview, issuesService.previewDelete, requestStructuralPreview, setStagedStructural])

  const cancelDraftReorder = useCallback(() => {
    setDraftReorder(null)
    setStructurePreviewError(null)
    setActionError(null)
    // Withdrawing a reorder withdraws the staged change. A delete preview
    // cancellation does not revoke the removal intent committed in the
    // destructive dialog: keep the draft dirty until Save or Discard.
    if (structuralEditRef.current?.type === 'reorder') {
      setStagedStructural(false)
    }
    cancelStructurePreview()
  }, [cancelStructurePreview, setStagedStructural])

  async function handleUndoEdit() {
    if (undoActions.length === 0 || isUndoing) return
    setIsUndoing(true)
    try {
      // Newest-first: a reorder made after a create is reversed before the
      // create's snapshot is restored (#5852).
      for (const action of undoActionsRef.current) {
        if (action.kind === 'snapshot') {
          await undoService.undo(action.sessionId, action.snapshotId)
        } else {
          await issuesService.reorder(threadId, action.issueIds)
        }
      }
      undoActionsRef.current = []
      setUndoActions([])
      const refreshed = await fetchAllIssues()
      baseIssuesRef.current = refreshed
      syncOptimisticIssues(refreshed, pendingMutationsRef.current)
      onIssueChanged?.()
    } catch (err: unknown) {
      console.error('[IssueToggleList] Error undoing edit:', err)
      setActionError(getApiErrorDetail(err))
    } finally {
      setIsUndoing(false)
    }
  }

  const handleDragStart = (issueId: number) => (event: DragEvent<HTMLButtonElement>) => {
    event.dataTransfer.effectAllowed = 'move'
    event.dataTransfer.setData('text/plain', String(issueId))
    setDraggedIssueId(issueId)
    setActionError(null)
  }

  const handleDragOver = (issueId: number) => (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    event.dataTransfer.dropEffect = 'move'
    setDragOverIssueId(issueId)
  }

  const handleDrop = (targetIssueId: number) => (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault()

    if (!draggedIssueId || draggedIssueId === targetIssueId) {
      setDraggedIssueId(null)
      setDragOverIssueId(null)
      return
    }

    const nextIssues = reorderIssuesForDrop(displayIssues, draggedIssueId, targetIssueId)
    setDraggedIssueId(null)
    setDragOverIssueId(null)

    // A resolved no-op drop is not a structural edit; do not preview or queue it.
    if (nextIssues.every((issue, index) => issue.id === displayIssues[index]?.id)) return
    requestStructuralEdit({ type: 'reorder', nextIssues })
  }

  const handleDragEnd = () => {
    setDraggedIssueId(null)
    setDragOverIssueId(null)
  }

  function handleDeleteIssue(issue: Issue) {
    setDeleteDialogIssue(issue)
  }

  function handleConfirmDelete() {
    if (!deleteDialogIssue) return

    const issueId = deleteDialogIssue.id
    // Close the destructive dialog before opening the preview: stacking two
    // modals would trap focus inside the Edit Series dialog (#3267). The delete
    // is queued only after the reader confirms the projected before/after rows,
    // but confirming "Remove from series" already stages a draft change: the
    // Edit Series close control must warn even while the preview is pending or
    // has failed (MQA-QUEUE-008 / #5864).
    setDeleteDialogIssue(null)
    setStagedStructural(true)
    requestStructuralEdit({ type: 'delete', issueId })
  }

  function handleCancelDelete() {
    // Opening a confirmation is not itself a change; only confirming the
    // removal stages one. Keep any earlier staged intent intact.
    setDeleteDialogIssue(null)
  }

  function handleMoveIssue(issue: Issue, direction: 'up' | 'down') {
    const nextIssues = moveIssueByStep(displayIssues, issue.id, direction)
    const didReorder = nextIssues.some(
      (candidate, index) => candidate.id !== displayIssues[index]?.id,
    )

    if (!didReorder) {
      focusMoveControl(issue.id, direction)
      return
    }

    requestStructuralEdit({
      type: 'reorder',
      nextIssues,
      announcement: `Moved issue #${issue.issue_number} ${direction}.`,
      focusTarget: { issueId: issue.id, direction },
    })

    if (!isExpanded && !isReorderMode) {
      const nextUnreadId = nextIssues.find((i) => i.status === 'unread')?.id ?? null
      const { startIndex, endIndex } = getVisibilityWindow(nextIssues, nextUnreadId)
      const movedIssueIndex = nextIssues.findIndex((i) => i.id === issue.id)
      const wouldBeVisible = movedIssueIndex >= startIndex && movedIssueIndex < endIndex

      if (!wouldBeVisible) {
        setIsExpanded(true)
      }
    }
  }

 if (isLoading) return <p className="text-xs text-[var(--theme-text-dim)]">Loading issues…</p>

  if (loadError) {
    return (
      <div className="space-y-2">
        <p className="text-[10px] font-bold uppercase tracking-widest text-[var(--theme-text-dim)]">Issues</p>
        <p className="text-xs text-[var(--theme-error)]">Could not load issues: {loadError}</p>
        {actionError && (
          <p
            className="text-xs text-[var(--theme-danger)]"
            data-testid="issue-action-error"
          >
            {actionError}
          </p>
        )}
        <button
          type="button"
          onClick={() => {
            void loadIssues()
          }}
          className="min-h-[36px] md:min-h-[44px] rounded-lg border border-[var(--theme-border)] px-3 text-xs font-bold text-[var(--theme-text-muted)] hover:text-[var(--theme-text-primary)] transition-colors"
          data-testid="issue-load-retry"
        >
          Retry
        </button>
      </div>
    )
  }

  const visibleIssues = getVisibleIssues()
  const hasHiddenIssues = displayIssues.length > 5 && !isExpanded && !isReorderMode

  return (
    <div className="space-y-2">
      <div className="flex justify-between items-center gap-2">
        <p className="text-[10px] font-bold uppercase tracking-widest text-[var(--theme-text-dim)]">Issues</p>
        <div className="flex items-center gap-2">
          {displayIssues.length > 5 && (
            <button
              type="button"
              onClick={() => setIsExpanded(!isExpanded)}
              className="text-[10px] font-black uppercase tracking-widest text-[var(--theme-comic-accent)] hover:text-[var(--theme-comic-accent)] transition-colors"
            >
              {isExpanded ? 'Show fewer' : `Show all ${displayIssues.length}`}
            </button>
          )}
          <button
            type="button"
            onClick={() => setIsReorderMode((previous) => !previous)}
            aria-pressed={isReorderMode}
            aria-label={isReorderMode ? 'Finish reordering issues' : 'Reorder issues'}
            data-testid="issue-reorder-toggle"
            className={[
              'min-h-[36px] md:min-h-[44px] px-2 rounded-lg border text-xs font-bold transition-colors',
              isReorderMode
                ? 'border-[var(--theme-comic-accent)]/60 bg-[var(--theme-comic-accent)]/10 text-[var(--theme-comic-accent)]'
                : 'border-[var(--theme-border)] text-[var(--theme-text-muted)] hover:text-[var(--theme-text-primary)]',
            ].join(' ')}
          >
            {isReorderMode ? 'Done' : 'Reorder'}
          </button>
        </div>
      </div>
      <p className="sr-only" aria-live="polite">{reorderAnnouncement}</p>
      <p className="text-[11px] text-[var(--theme-text-dim)]">Read states: marked read = read without rating; read &amp; rated = read with rating; still unread = not read.</p>
      {hasHiddenIssues && (
        <p className="text-xs text-[var(--theme-text-dim)] italic">Showing {visibleIssues.length} of {issues.length} issues around your current position</p>
      )}
      {issues.length === 0 && (
        <p className="text-xs text-[var(--theme-text-dim)]">No issues yet. Add the first range below.</p>
      )}
      {isReorderMode ? (
        <div className="space-y-1 max-h-64 overflow-auto" data-testid="issue-reorder-list">
          {displayIssues.map((issue, index) => {
            const isBusy = toggling.has(issue.id) || deleting.has(issue.id)

            return (
              <div
                key={issue.id}
                data-testid={`issue-reorder-row-${issue.id}`}
                data-issue-number={issue.issue_number}
                className="surface-panel flex flex-wrap items-center gap-2 px-2 min-h-[44px]"
              >
                <span className="text-xs font-bold text-[var(--theme-text-primary)]">
                  #{issue.issue_number}
                </span>
                <span className="text-[10px] text-[var(--theme-text-muted)]">
                  {issue.status === 'read' ? '✅ Read' : '🟢 Unread'}
                </span>
                <CompactIssueCardTrigger
                  issueId={issue.id}
                  card={cardsByIssue.get(issue.id)}
                  threadTitle={cardsByIssue.get(issue.id)?.thread_title ?? 'Comic'}
                  issueNumber={issue.issue_number}
                  status={issue.status === 'read' ? 'read' : 'unread'}
                  onMutated={onDirectIssueMutated}
                />
                <span className="flex-1" />
                <button
                  type="button"
                  onClick={() => handleMoveIssue(issue, 'up')}
                  disabled={isBusy || index === 0}
                  className={[
                    'min-h-[44px] min-w-[44px] flex items-center justify-center text-xs font-black transition-colors',
                    'text-[var(--theme-text-muted)] hover:text-[var(--theme-comic-accent)] disabled:opacity-40',
                  ].join(' ')}
                  aria-label={`Move issue #${issue.issue_number} up`}
                  data-testid={`issue-move-up-${issue.id}`}
                  data-move-control={`up-${issue.id}`}
                  title={`Move issue #${issue.issue_number} up`}
                >
                  ↑
                </button>
                <button
                  type="button"
                  onClick={() => handleMoveIssue(issue, 'down')}
                  disabled={isBusy || index === displayIssues.length - 1}
                  className={[
                    'min-h-[44px] min-w-[44px] flex items-center justify-center text-xs font-black transition-colors',
                    'text-[var(--theme-text-muted)] hover:text-[var(--theme-comic-accent)] disabled:opacity-40',
                  ].join(' ')}
                  aria-label={`Move issue #${issue.issue_number} down`}
                  data-testid={`issue-move-down-${issue.id}`}
                  data-move-control={`down-${issue.id}`}
                  title={`Move issue #${issue.issue_number} down`}
                >
                  ↓
                </button>
              </div>
            )
          })}
        </div>
      ) : (
      <div className="flex flex-wrap gap-1 max-h-40 overflow-auto">
        {visibleIssues.map((issue) => {
    const fullIndex = displayIssues.findIndex((i) => i.id === issue.id)
    const isBusy = toggling.has(issue.id) || deleting.has(issue.id)
    const isDragOver = dragOverIssueId === issue.id
    const isDragged = draggedIssueId === issue.id
    const canMoveUp = fullIndex > 0
    const canMoveDown = fullIndex < displayIssues.length - 1
    const hasDeps = dependencies[issue.id] !== undefined
    const tooltipContent = getDependencyTooltip(dependencies[issue.id])

          return (
            <div
              key={issue.id}
              data-testid={`issue-pill-${issue.id}`}
              data-issue-number={issue.issue_number}
              className={[
                'flex flex-wrap items-center rounded border transition-all',
                issue.status === 'read'
                  ? 'bg-[var(--theme-comic-accent)]/20 border-[var(--theme-comic-accent)]/30 text-[var(--theme-comic-accent)]'
                  : 'bg-[var(--theme-bg-hover)] border-[var(--theme-border)] text-[var(--theme-text-muted)]',
                isDragOver ? 'border-[var(--theme-comic-accent)]/60 bg-[var(--theme-comic-accent)]/10' : '',
                isDragged ? 'opacity-60' : '',
                isBusy ? 'opacity-50' : '',
              ].join(' ')}
              onDragOver={handleDragOver(issue.id)}
              onDrop={handleDrop(issue.id)}
            >
                 <button
                   type="button"
                   draggable={!isBusy}
                   onDragStart={handleDragStart(issue.id)}
                   onDragEnd={handleDragEnd}
                   onClick={() => handleToggle(issue)}
                   disabled={isBusy}
                   className={[
                     'min-h-[36px] md:min-h-[44px] min-w-[36px] md:min-w-[44px] flex items-center justify-center px-2 py-0.5 text-xs font-bold transition-all',
                     isBusy ? '' : 'hover:opacity-80 cursor-grab active:cursor-grabbing',
                   ].join(' ')}
                    title={`#${issue.issue_number}: ${issue.status}. Reorder with the arrow buttons or by dragging.`}
                   aria-label={`Toggle issue #${issue.issue_number}`}
                   data-testid={`issue-toggle-${issue.id}`}
                 >
                   #{issue.issue_number} {issue.status === 'read' ? '✅' : '🟢'}
                 </button>
                 <CompactIssueCardTrigger
                   issueId={issue.id}
                   card={cardsByIssue.get(issue.id)}
                   threadTitle={cardsByIssue.get(issue.id)?.thread_title ?? 'Comic'}
                   issueNumber={issue.issue_number}
                   status={issue.status === 'read' ? 'read' : 'unread'}
                   onMutated={onDirectIssueMutated}
                 />
              {hasDeps && tooltipContent && (
                <>
                  <Tooltip content={tooltipContent}>
                    <button
                      type="button"
                      className="dependency-indicator min-h-[36px] md:min-h-[44px] min-w-[28px] md:min-w-[44px] px-1 text-[10px] opacity-70 hover:opacity-100 cursor-help"
                      onClick={(e) => {
                        e.stopPropagation()
                        setSelectedDepsIssue(issue)
                      }}
                      title="Has dependencies (click for details)"
                      aria-label={`View dependencies for issue #${issue.issue_number}`}
                    >
                      🔗
                    </button>
                  </Tooltip>
                </>
              )}
               <div className="hidden md:flex border-l border-[var(--theme-border)]">
                 <button
                   type="button"
                   onClick={() => handleMoveIssue(issue, 'up')}
                   disabled={isBusy || !canMoveUp}
                   className={[
                     'min-h-[44px] min-w-[44px] flex items-center justify-center text-[11px] font-black text-[var(--theme-text-dim)] transition-colors',
                     'hover:text-[var(--theme-comic-accent)] disabled:opacity-40',
                   ].join(' ')}
                   aria-label={`Move issue #${issue.issue_number} up`}
                   data-testid={`issue-move-up-${issue.id}`}
                   data-move-control={`up-${issue.id}`}
                   title={`Move issue #${issue.issue_number} up`}
                 >
                   ↑
                 </button>
                 <button
                   type="button"
                   onClick={() => handleMoveIssue(issue, 'down')}
                   disabled={isBusy || !canMoveDown}
                   className={[
                     'min-h-[44px] min-w-[44px] flex items-center justify-center text-[11px] font-black text-[var(--theme-text-dim)] transition-colors',
                     'hover:text-[var(--theme-comic-accent)] disabled:opacity-40',
                   ].join(' ')}
                   aria-label={`Move issue #${issue.issue_number} down`}
                   data-testid={`issue-move-down-${issue.id}`}
                   data-move-control={`down-${issue.id}`}
                   title={`Move issue #${issue.issue_number} down`}
                 >
                   ↓
                 </button>
               </div>
               <button
                 type="button"
                 onClick={() => {
                   void handleDeleteIssue(issue)
                 }}
                 disabled={deleting.has(issue.id)}
                 className={[
                   'min-h-[36px] md:min-h-[44px] min-w-[28px] md:min-w-[44px] flex items-center justify-center pr-2 text-[10px] font-black text-[var(--theme-text-dim)] transition-colors',
                   'hover:text-[var(--theme-error)] disabled:opacity-50',
                 ].join(' ')}
                 aria-label={`Delete issue #${issue.issue_number}`}
                 data-testid={`issue-delete-${issue.id}`}
                 title={`Delete issue #${issue.issue_number}`}
               >
                 x
               </button>
             </div>
           )
         })}
      </div>
      )}
      {draftReorder && (
        <div
          className="rounded-lg border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] p-3 space-y-2"
          data-testid="pending-reorder-preview"
        >
          <p className="text-xs font-bold text-[var(--theme-text-primary)]">
            Pending order change — not saved
          </p>
          <div className="flex flex-wrap gap-1.5">
            {pendingReorderEffects.length === 0 ? (
              <span className="text-xs text-[var(--theme-text-muted)]">Review the new order above before saving.</span>
            ) : pendingReorderEffects.map((effect) => (
              <span
                key={effect.id}
                className="rounded border border-[var(--theme-border)] px-2 py-1 text-xs text-[var(--theme-text-muted)]"
                data-testid={`pending-reorder-effect-${effect.id}`}
              >
                #{effect.issueNumber}: {effect.before} → {effect.after}
              </span>
            ))}
          </div>
          <button
            type="button"
            onClick={cancelDraftReorder}
            className="min-h-9 rounded-lg border border-[var(--theme-border)] px-3 py-1.5 text-xs font-bold text-[var(--theme-text-primary)] hover:bg-[var(--theme-bg-hover)] transition-colors"
            data-testid="undo-pending-reorder"
          >
            Undo reorder
          </button>
        </div>
      )}
      <div className="flex gap-2">
        <label htmlFor={addInputId} className="sr-only">
          Add issues
        </label>
        <input
          id={addInputId}
          type="text"
          value={addRange}
          onChange={(e) => {
            setAddRange(e.target.value)
            setAddError(null)
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              e.stopPropagation()
              void handleAddIssues()
            }
          }}
          placeholder="Add: 19-24 or 0, Annual 1"
          aria-invalid={addValidationError || addError ? true : undefined}
          aria-describedby={addErrorDescription}
          className="flex-1 bg-[var(--theme-bg-hover)] border border-[var(--theme-border)] rounded-lg px-2 py-3 md:py-4 text-xs text-[var(--theme-text-primary)]"
          data-testid="issue-add-input"
        />
        <button
          type="button"
          onClick={() => handleAddIssues()}
          disabled={isAdding || isPreviewing || !addRange.trim() || !isAddRangeValid}
          className="px-3 py-3 md:py-4 bg-[var(--theme-bg-hover)] border border-[var(--theme-border)] rounded-lg text-xs font-bold text-[var(--theme-text-primary)] hover:bg-[var(--theme-bg-hover)] disabled:opacity-50"
          data-testid="issue-add-button"
        >
          {(isAdding || isPreviewing) ? '…' : 'Add'}
        </button>
      </div>
      {undoActions.length > 0 && (
        <PostCreateUndoBar
          isUndoing={isUndoing}
          onUndo={() => void handleUndoEdit()}
        />
      )}
      {addValidationError && (
        <p
          id={addValidationErrorId}
          className="text-xs text-[var(--theme-danger)]"
          role="alert"
          data-testid="issue-add-validation-error"
        >
          {addValidationError}
        </p>
      )}
      {addError && (
        <p id={addServerErrorId} className="text-xs text-[var(--theme-danger)]" data-testid="issue-add-error">
          {addError}
        </p>
      )}
      {deferred && pendingCreates.length > 0 && (
        <div className="flex flex-wrap gap-1.5" data-testid="pending-creates">
          {pendingCreates.map((range, index) => (
            <span
              // SAFETY: pending create ranges are display-only; index keys are stable for this list.
              key={`${range}-${index}`}
              className="rounded-lg border border-[var(--theme-comic-accent)]/50 bg-[var(--theme-comic-accent)]/30 px-2 py-1 text-xs text-[var(--theme-comic-accent)]"
              title="Will be added when you save"
            >
              + {range} (pending)
            </span>
          ))}
        </div>
      )}
      {actionError && (
        <p className="text-xs text-[var(--theme-danger)]" data-testid="issue-action-error">{actionError}</p>
      )}
      {selectedDepsIssue && (
        <Modal
          isOpen={selectedDepsIssue !== null}
          title={`Dependencies for Issue #${selectedDepsIssue.issue_number}`}
          onClose={() => setSelectedDepsIssue(null)}
          data-testid="dependency-modal"
        >
          <div className="space-y-4">
            {dependencies[selectedDepsIssue.id]?.incoming &&
              dependencies[selectedDepsIssue.id].incoming.length > 0 && (
                <div>
                  <h3 className="text-sm font-bold text-[var(--theme-text-primary)] mb-2">Blocked by</h3>
                  <ul className="space-y-1">
                    {dependencies[selectedDepsIssue.id].incoming.map((edge) => (
                      <li key={edge.dependency_id} className="text-xs text-[var(--theme-text-muted)]">
                        ← {edge.source_thread_title} #{edge.source_issue_number}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            {dependencies[selectedDepsIssue.id]?.outgoing &&
              dependencies[selectedDepsIssue.id].outgoing.length > 0 && (
                <div>
                  <h3 className="text-sm font-bold text-[var(--theme-text-primary)] mb-2">Blocking</h3>
                  <ul className="space-y-1">
                    {dependencies[selectedDepsIssue.id].outgoing.map((edge) => (
                      <li key={edge.dependency_id} className="text-xs text-[var(--theme-text-muted)]">
                        → {edge.source_thread_title} #{edge.source_issue_number}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            {(!dependencies[selectedDepsIssue.id]?.incoming ||
              dependencies[selectedDepsIssue.id].incoming.length === 0) &&
              (!dependencies[selectedDepsIssue.id]?.outgoing ||
                dependencies[selectedDepsIssue.id].outgoing.length === 0) && (
                <p className="text-xs text-[var(--theme-text-dim)]">No dependencies found</p>
              )}
            <div className="pt-2 border-t border-[var(--theme-border)]">
              <p className="text-[10px] font-bold uppercase tracking-widest text-[var(--theme-text-dim)] mb-2">Manage dependencies</p>
              {onOpenDependencies ? (
                <button
                  type="button"
                  onClick={() => {
                    setSelectedDepsIssue(null)
                    onOpenDependencies()
                  }}
                  className="w-full py-2 rounded-lg border border-[var(--theme-border)] text-xs font-bold text-[var(--theme-text-muted)] hover:text-[var(--theme-text-primary)] transition-colors text-left"
                  data-testid="open-dependency-builder"
                >
                  Open Dependency Builder →
                </button>
              ) : (
                <p className="text-xs text-[var(--theme-text-dim)]">
                  Save a Reading Plan or use the Dependency Builder from the Queue to create and manage prerequisites.
                </p>
              )}
            </div>
          </div>
        </Modal>
      )}
      {previewError && (
        <IssuePreviewErrorModal
          message={previewError}
          range={addRange}
          isPreviewing={isPreviewing}
          onCancel={() => { setPreviewError(null); setAddError(null) }}
          onRetry={() => { setAddError(null); void handleAddIssues() }}
        />
      )}
      {previewState && (
        <IssueCreatePreviewModal
          state={previewState}
          isPreviewing={isPreviewing}
          acceptedAliasNumbers={acceptedAliasNumbers}
          onSelectStrategy={(strategy) => setPreviewState({ ...previewState, selectedStrategy: strategy })}
          onToggleAlias={toggleAliasOffer}
          onConfirm={handleConfirmPreview}
          onCancel={closePreview}
        />
      )}
      {structurePreview && (
        <IssueStructurePreviewModal
          kind={structurePreview.edit.type}
          response={structurePreview.response}
          isPreviewing={isPreviewingStructure}
          onConfirm={() => {
            confirmStructurePreview()
            setDraftReorder(null)
            setStructurePreviewError(null)
          }}
          onCancel={cancelDraftReorder}
        />
      )}
      {structurePreviewError && structuralEditRef.current && (
        <Modal
          isOpen
          title="Preview unavailable"
          onClose={cancelDraftReorder}
          data-testid="edit-series-structure-preview-error-modal"
        >
          <div className="space-y-4">
            <p className="text-sm text-[var(--theme-text-muted)]" role="alert">
              Could not preview this issue change: {structurePreviewError}
            </p>
            <p className="text-xs text-[var(--theme-text-muted)]">
              {structuralEditRef.current.type === 'reorder'
                ? 'The proposed order is shown above but has not been saved. Retry the preview, or undo it.'
                : 'Nothing was changed. Retry the preview or cancel.'}
            </p>
            <div className="flex flex-col-reverse sm:flex-row gap-2 sm:justify-end">
              <button
                type="button"
                onClick={cancelDraftReorder}
                className="min-h-11 sm:min-h-9 rounded-lg border border-[var(--theme-border)] px-4 py-2 text-xs font-bold text-[var(--theme-text-muted)] hover:text-[var(--theme-text-primary)] transition-colors"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => {
                  const edit = structuralEditRef.current
                  if (!edit) return
                  setStructurePreviewError(null)
                  requestStructuralEdit(edit)
                }}
                disabled={isPreviewingStructure}
                className="min-h-11 sm:min-h-9 rounded-lg bg-[var(--theme-primary-action)] px-4 py-2 text-xs font-black text-[var(--theme-primary-action-text)] hover:bg-[var(--theme-primary-action-hover)] disabled:opacity-60 transition-colors"
                data-testid="retry-structure-preview"
              >
                Retry preview
              </button>
            </div>
          </div>
        </Modal>
      )}
      <DeleteIssueDialog
        issue={deleteDialogIssue}
        onConfirm={handleConfirmDelete}
        onCancel={handleCancelDelete}
        deferred={deferred}
      />
    </div>
  )
})
