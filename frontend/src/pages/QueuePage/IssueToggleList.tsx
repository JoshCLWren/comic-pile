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
import type { IssueListParams } from '../../services/api-issues'
import { issueDependenciesApi } from '../../services/api-dependencies'
import type { ThreadIssueDependenciesResponse } from '../../services/api-dependencies'
import { getApiErrorDetail } from '../../utils/apiError'
import { validateIssueRangeForStaging } from '../../utils/issueParser'
import { isWindowDefined, isFunction } from '../../utils/runtimeChecks'
import Tooltip from '../../components/Tooltip'
import Modal from '../../components/Modal'
import DeleteIssueDialog from './DeleteIssueDialog'
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

/** The issue-API surface IssueToggleList consumes, injectable for tests. */
export interface IssueToggleListApi {
  list: (
    threadId: number,
    params?: { status?: 'unread' | 'read'; page_size?: number; page_token?: string },
  ) => Promise<IssueListResponse>
  create: (
    threadId: number,
    issueRange: string,
    options?: { insert_after_issue_id?: number | null },
  ) => Promise<IssueListResponse>
  markRead: (issueId: number) => Promise<void>
  markUnread: (issueId: number) => Promise<void>
  delete: (issueId: number) => Promise<void>
  reorder: (threadId: number, issueIds: number[]) => Promise<void>
}

/** The dependency-API surface IssueToggleList consumes, injectable for tests. */
export interface IssueToggleListDependenciesApi {
  listForThread: (threadId: number) => Promise<ThreadIssueDependenciesResponse>
}

/** Imperative handle for deferred (draft) mode. */
export interface IssueToggleListHandle {
  /** Flush queued mutations to the server. Resolves when complete. */
  flush: () => Promise<void>
  /** Whether any mutations are queued. */
  hasPendingMutations: () => boolean
}

export const IssueToggleList = forwardRef<IssueToggleListHandle, {
  threadId: number
  onOpenDependencies?: () => void
  onIssueChanged?: () => void
  onLoad?: () => void
  /** Injectable issue API; defaults to the production issuesApi. */
  issuesApi?: IssueToggleListApi
  /** Injectable dependency API; defaults to the production issueDependenciesApi. */
  dependenciesApi?: IssueToggleListDependenciesApi
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
  issuesApi: issuesService = issuesApi,
  dependenciesApi = issueDependenciesApi,
  deferred = false,
}, ref) {
  const [issues, setIssues] = useState<Issue[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [addRange, setAddRange] = useState('')
  const [isAdding, setIsAdding] = useState(false)
  const [addError, setAddError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  // Set when a failed change could not be followed by a complete resync, so
  // the reader gets a visible reload path instead of a Save that stays blocked
  // with no explanation (#4030).
  const [isReloadRequired, setIsReloadRequired] = useState(false)
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
  const baseIssuesRef = useRef<Issue[]>([])
  const pendingMutationsRef = useRef<IssueMutation[]>([])
  const isProcessingMutationsRef = useRef(false)
  const nextMutationIdRef = useRef(1)
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
    return issues.find((issue) => issue.status === 'unread')?.id ?? null
  }, [issues])

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
    if (isExpanded || issues.length <= 5) {
      return issues
    }

    const nextUnreadId = getNextUnreadIssueId()
    const { startIndex, endIndex } = getVisibilityWindow(issues, nextUnreadId)

    return issues.slice(startIndex, endIndex)
  }, [issues, isExpanded, getNextUnreadIssueId, getVisibilityWindow])

  const [pendingCreates, setPendingCreates] = useState<string[]>([])

  const syncOptimisticIssues = useCallback((baseIssues: Issue[], pendingMutations: IssueMutation[]) => {
    setIssues(applyIssueMutations(baseIssues, pendingMutations))
    setToggling(getPendingIssueIds(pendingMutations, 'toggle'))
    setDeleting(getPendingIssueIds(pendingMutations, 'delete'))
    setPendingCreates(getPendingCreates(pendingMutations))
  }, [])

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
      case 'reorder':
        await issuesService.reorder(threadId, normalizeIssueOrder(baseIssuesRef.current, mutation.issueIds))
        return
      case 'create':
        await issuesService.create(threadId, mutation.issueRange)
        return
    }
  }, [issuesService, threadId])

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
            const refreshed = await fetchAllIssues()
            const expectedTotal = totalCountRef.current
            if (expectedTotal > 0 && refreshed.length < expectedTotal) {
              throw new Error('Could not load all issues; save aborted.')
            }
            baseIssuesRef.current = refreshed
          } else {
            baseIssuesRef.current = applyIssueMutation(baseIssuesRef.current, currentMutation)
          }
          hadSuccess = true
        } catch (err: unknown) {
          // A failed mutation stops the queue and is reported to the caller:
          // the mutations that were not applied stay queued so the reader can
          // retry them, and the rejected flush keeps the Edit Series dialog
          // open instead of closing it over a lost create.
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
          } catch (refreshErr) {
            // The failed mutation is the root cause; the failed resync is a
            // secondary failure. Report the root cause to the reader and keep
            // both failures in the log, so the reason the save stopped is
            // never lost behind the resync error (#3764).
            //
            // The base list can no longer be trusted after an incomplete or
            // failed resync, so later saves stay blocked until a complete
            // reload. Surface that reload path instead of clearing the flag
            // silently: without it the reader would have to close the dialog
            // and lose every queued edit (#4030).
            fullyLoadedRef.current = false
            setIsReloadRequired(true)
            console.error(
              '[IssueToggleList] Mutation failed and the follow-up resync also failed:',
              { mutationError: err, resyncError: refreshErr },
            )
            setActionError(getApiErrorDetail(err))
            throw new Error(
              `${getApiErrorDetail(err)} (issue list resync failed: ${getApiErrorDetail(refreshErr)})`,
            )
          }
          // The resync returned the complete issue list, so the base list is
          // fresh and the loaded flag must stay true. Clearing it here used to
          // leave every later Save failing the load guard with no reload path
          // in the deferred editor (#4030).
          fullyLoadedRef.current = true
          setIsReloadRequired(false)
          setActionError(getApiErrorDetail(err))
          throw err
        } finally {
          pendingMutationsRef.current = pendingMutationsRef.current.filter(
            (mutation) => mutation.id !== currentMutation.id
          )
          syncOptimisticIssues(baseIssuesRef.current, pendingMutationsRef.current)
        }
      }
    } finally {
      isProcessingMutationsRef.current = false
      if (hadSuccess) {
        onIssueChanged?.()
      }
    }
  }, [fetchAllIssues, runIssueMutation, syncOptimisticIssues, onIssueChanged])

  const enqueueIssueMutation = useCallback((mutation: QueuedIssueMutation) => {
    // SAFETY: spreading the queued mutation and adding the sequential id satisfies the IssueMutation contract.
    const queuedMutation = {
      ...mutation,
      id: nextMutationIdRef.current++,
    } as IssueMutation

    pendingMutationsRef.current = [...pendingMutationsRef.current, queuedMutation]
    syncOptimisticIssues(baseIssuesRef.current, pendingMutationsRef.current)
    if (!deferred) {
      // Immediate mode has no caller awaiting the queue, so a failed flush
      // must not escape as an unhandled rejection. The inline action error
      // already reports the failure, and the mutations that were not applied
      // stay queued for the next attempt.
      void processIssueMutations().catch(() => undefined)
    }
  }, [processIssueMutations, syncOptimisticIssues, deferred])

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
      setIsReloadRequired(false)
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
    if (deferred) {
      // Draft mode: queue the create; it flushes on dialog Save.
      // The range input clears immediately for the next entry.
      enqueueIssueMutation({ type: 'create', issueRange: range })
      setAddRange('')
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

    const nextIssues = reorderIssuesForDrop(issues, draggedIssueId, targetIssueId)
    setDraggedIssueId(null)
    setDragOverIssueId(null)

    enqueueIssueReorder(nextIssues)
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

    setActionError(null)
    enqueueIssueMutation({
      type: 'delete',
      issueId: deleteDialogIssue.id,
    })
    // Confirming is the destructive action, so close right away. The pill is
    // already removed optimistically and a failed delete is restored by the
    // refetch in `processIssueMutations` with its message in the inline action
    // error. Holding the dialog open until the delete settles would also trap
    // focus: inside the Edit Series dialog the delete is a draft that only
    // flushes on Save Changes (#3267), which a modal on top would block.
    setDeleteDialogIssue(null)
  }

  function handleCancelDelete() {
    setDeleteDialogIssue(null)
  }

  function handleMoveIssue(issue: Issue, direction: 'up' | 'down') {
    const nextIssues = moveIssueByStep(issues, issue.id, direction)
    const didReorder = enqueueIssueReorder(nextIssues, {
      announcement: `Moved issue #${issue.issue_number} ${direction}.`,
      focusTarget: { issueId: issue.id, direction },
    })

    if (!didReorder) {
      focusMoveControl(issue.id, direction)
      return
    }

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

 if (isLoading) return <p className="text-xs text-stone-500">Loading issues…</p>

  if (loadError) {
    return (
      <div className="space-y-2">
        <p className="text-[10px] font-bold uppercase tracking-widest text-stone-500">Issues</p>
        <p className="text-xs text-red-400">Could not load issues: {loadError}</p>
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
  const hasHiddenIssues = issues.length > 5 && !isExpanded && !isReorderMode

  return (
    <div className="space-y-2">
      {isReloadRequired && (
        <div className="space-y-2" data-testid="issue-reload-required">
          <p className="text-xs text-[var(--theme-warning)]">
            The issue list could not be reloaded after a failed change. Reload it before
            saving again.
          </p>
          <button
            type="button"
            onClick={() => {
              void loadIssues()
            }}
            className="min-h-[36px] md:min-h-[44px] rounded-lg border border-[var(--theme-border)] px-3 text-xs font-bold text-[var(--theme-text-muted)] hover:text-[var(--theme-text-primary)] transition-colors"
            data-testid="issue-reload-button"
          >
            Reload issues
          </button>
        </div>
      )}
      <div className="flex justify-between items-center gap-2">
        <p className="text-[10px] font-bold uppercase tracking-widest text-stone-500">Issues</p>
        <div className="flex items-center gap-2">
          {issues.length > 5 && (
            <button
              type="button"
              onClick={() => setIsExpanded(!isExpanded)}
              className="text-[10px] font-black uppercase tracking-widest text-amber-400 hover:text-amber-300 transition-colors"
            >
              {isExpanded ? 'Show fewer' : `Show all ${issues.length}`}
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
                ? 'border-amber-400/60 bg-amber-500/10 text-amber-300'
                : 'border-[var(--theme-border)] text-[var(--theme-text-muted)] hover:text-[var(--theme-text-primary)]',
            ].join(' ')}
          >
            {isReorderMode ? 'Done' : 'Reorder'}
          </button>
        </div>
      </div>
      <p className="sr-only" aria-live="polite">{reorderAnnouncement}</p>
      {hasHiddenIssues && (
        <p className="text-xs text-stone-500 italic">
          Showing {visibleIssues.length} of {issues.length} issues around your current position
        </p>
      )}
      {issues.length === 0 && (
        <p className="text-xs text-stone-500">No issues yet. Add the first range below.</p>
      )}
      {isReorderMode ? (
        <div className="space-y-1 max-h-64 overflow-auto" data-testid="issue-reorder-list">
          {issues.map((issue, index) => {
            const isBusy = toggling.has(issue.id) || deleting.has(issue.id)

            return (
              <div
                key={issue.id}
                data-testid={`issue-reorder-row-${issue.id}`}
                data-issue-number={issue.issue_number}
                className="surface-panel flex items-center gap-2 px-2 min-h-[44px]"
              >
                <span className="text-xs font-bold text-[var(--theme-text-primary)]">
                  #{issue.issue_number}
                </span>
                <span className="text-[10px] text-[var(--theme-text-muted)]">
                  {issue.status === 'read' ? '✅ Read' : '🟢 Unread'}
                </span>
                <span className="flex-1" />
                <button
                  type="button"
                  onClick={() => handleMoveIssue(issue, 'up')}
                  disabled={isBusy || index === 0}
                  className={[
                    'min-h-[44px] min-w-[44px] flex items-center justify-center text-xs font-black transition-colors',
                    'text-[var(--theme-text-muted)] hover:text-amber-300 disabled:opacity-40',
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
                  disabled={isBusy || index === issues.length - 1}
                  className={[
                    'min-h-[44px] min-w-[44px] flex items-center justify-center text-xs font-black transition-colors',
                    'text-[var(--theme-text-muted)] hover:text-amber-300 disabled:opacity-40',
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
    const fullIndex = issues.findIndex((i) => i.id === issue.id)
    const isBusy = toggling.has(issue.id) || deleting.has(issue.id)
    const isDragOver = dragOverIssueId === issue.id
    const isDragged = draggedIssueId === issue.id
    const canMoveUp = fullIndex > 0
    const canMoveDown = fullIndex < issues.length - 1
    const hasDeps = dependencies[issue.id] !== undefined
    const tooltipContent = getDependencyTooltip(dependencies[issue.id])

          return (
            <div
              key={issue.id}
              data-testid={`issue-pill-${issue.id}`}
              data-issue-number={issue.issue_number}
              className={[
                'flex items-center rounded border transition-all',
                issue.status === 'read'
                  ? 'bg-amber-600/20 border-amber-500/30 text-amber-400'
                  : 'bg-white/5 border-white/10 text-stone-400',
                isDragOver ? 'border-amber-400/60 bg-amber-500/10' : '',
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
               <div className="hidden md:flex border-l border-white/10">
                 <button
                   type="button"
                   onClick={() => handleMoveIssue(issue, 'up')}
                   disabled={isBusy || !canMoveUp}
                   className={[
                     'min-h-[44px] min-w-[44px] flex items-center justify-center text-[11px] font-black text-stone-500 transition-colors',
                     'hover:text-amber-300 disabled:opacity-40',
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
                     'min-h-[44px] min-w-[44px] flex items-center justify-center text-[11px] font-black text-stone-500 transition-colors',
                     'hover:text-amber-300 disabled:opacity-40',
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
                   'min-h-[36px] md:min-h-[44px] min-w-[28px] md:min-w-[44px] flex items-center justify-center pr-2 text-[10px] font-black text-stone-500 transition-colors',
                   'hover:text-red-300 disabled:opacity-50',
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
          className="flex-1 bg-white/5 border border-white/10 rounded-lg px-2 py-3 md:py-4 text-xs text-stone-300"
          data-testid="issue-add-input"
        />
        <button
          type="button"
          onClick={() => handleAddIssues()}
          disabled={isAdding || !addRange.trim() || !isAddRangeValid}
          className="px-3 py-3 md:py-4 bg-white/5 border border-white/10 rounded-lg text-xs font-bold text-stone-300 hover:bg-white/10 disabled:opacity-50"
          data-testid="issue-add-button"
        >
          {isAdding ? '…' : 'Add'}
        </button>
      </div>
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
              className="rounded-lg border border-amber-700/50 bg-amber-950/30 px-2 py-1 text-xs text-amber-200"
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
                  <h3 className="text-sm font-bold text-stone-300 mb-2">Blocked by</h3>
                  <ul className="space-y-1">
                    {dependencies[selectedDepsIssue.id].incoming.map((edge) => (
                      <li key={edge.dependency_id} className="text-xs text-stone-400">
                        ← {edge.source_thread_title} #{edge.source_issue_number}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            {dependencies[selectedDepsIssue.id]?.outgoing &&
              dependencies[selectedDepsIssue.id].outgoing.length > 0 && (
                <div>
                  <h3 className="text-sm font-bold text-stone-300 mb-2">Blocking</h3>
                  <ul className="space-y-1">
                    {dependencies[selectedDepsIssue.id].outgoing.map((edge) => (
                      <li key={edge.dependency_id} className="text-xs text-stone-400">
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
                <p className="text-xs text-stone-500">No dependencies found</p>
              )}
            <div className="pt-2 border-t border-white/10">
              <p className="text-[10px] font-bold uppercase tracking-widest text-stone-500 mb-2">Manage dependencies</p>
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
                <p className="text-xs text-stone-500">
                  Save a Reading Plan or use the Dependency Builder from the Queue to create and manage prerequisites.
                </p>
              )}
            </div>
          </div>
        </Modal>
      )}
      <DeleteIssueDialog
        issue={deleteDialogIssue}
        onConfirm={handleConfirmDelete}
        onCancel={handleCancelDelete}
      />
    </div>
  )
})
