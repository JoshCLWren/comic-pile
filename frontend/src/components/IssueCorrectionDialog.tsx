import { useState, useCallback, useEffect } from 'react'
import type { KeyboardEvent } from 'react'
import Modal from './Modal'
import CompactIssueCardTrigger from './CompactIssueCardTrigger'
import { issuesApi } from '../services/api-issues'
import type { IssueListParams, IssueReadOperationResponse, IssueReadOperationUndoResponse } from '../services/api-issues'
import { issueCardsApi } from '../services/issueCardsApi'
import { issueDependenciesApi } from '../services/api-dependencies'
import { getApiErrorStatus } from '../utils/apiError'
import {
  clearBulkReadReceipt,
  findBulkReadReceipt,
  writeBulkReadReceipt,
} from '../hooks/useBulkReadOperations'
import type { Issue, IssueListResponse } from '../types'

export interface IssueCorrectionIssuesApi {
  list: (threadId: number, params?: IssueListParams) => Promise<IssueListResponse>
  create: (
    threadId: number,
    issueRange: string,
    options?: { insert_after_issue_id?: number | null },
  ) => Promise<IssueListResponse>
  markRead: (issueId: number) => Promise<void>
  markUnread: (issueId: number) => Promise<void>
  bulkMarkRead: (issueIds: number[]) => Promise<IssueReadOperationResponse>
  bulkMarkUnread: (issueIds: number[]) => Promise<IssueReadOperationResponse>
  move: (issueId: number, afterIssueId: number | null) => Promise<void>
  getReadOperation?: (operationId: number) => Promise<IssueReadOperationResponse>
  undoReadOperation?: (operationId: number) => Promise<IssueReadOperationUndoResponse>
}

export interface IssueCorrectionDependenciesApi {
  // Real `/v1/threads/{thread_id}/issue-dependencies` wire shape: each issue
  // carries `incoming`/`outgoing` edges, not a flat `dependencies` array.
  listForThread: (threadId: number) => Promise<{
    issues?: Array<{
      issue_id: number
      incoming?: Array<{ source_issue_id?: number }>
      outgoing?: Array<{
        source_issue_id?: number
        source_issue_number?: string
        source_thread_title?: string
      }>
    }>
  }>
}

export interface IssueCorrectionCardsApi {
  fetchCards: (issueIds: number[]) => Promise<Array<{ issue_id: number; rating?: number | null }>>
}

interface ProjectedCorrection {
  orderedIssues: Issue[]
  targetIssue: Issue
  /** Anchor handed to create; null means append at the end. */
  createAfterIssueId: number | null
}

interface ReviewedCorrection {
  ids: number[]
  version: string
}

/**
 * Project the selected insertion position onto one fresh issue list. Preview
 * and confirmation both use this projection, so the reviewed affected set and
 * the mutation can never disagree about where the target lands (#4655 F2/R3).
 */
function projectCorrection(
  issues: Issue[],
  targetNumber: string,
  insertPosition: string,
): ProjectedCorrection {
  const existing = issues.find((issue) => issue.issue_number === targetNumber)
  if (existing) {
    return { orderedIssues: issues, targetIssue: existing, createAfterIssueId: null }
  }

  // SAFETY: sentinel id identifies the proposed target in the preview only.
  const proposed = { id: -1, issue_number: targetNumber, status: 'unread' } as Issue
  const projected = [...issues]
  if (insertPosition === 'start') {
    projected.unshift(proposed)
    return { orderedIssues: projected, targetIssue: proposed, createAfterIssueId: null }
  }

  const anchorId =
    insertPosition !== 'end' && insertPosition !== '' ? Number(insertPosition) : null
  const anchorIndex =
    anchorId !== null && Number.isFinite(anchorId)
      ? projected.findIndex((issue) => issue.id === anchorId)
      : -1
  if (anchorIndex >= 0) {
    projected.splice(anchorIndex + 1, 0, proposed)
    return { orderedIssues: projected, targetIssue: proposed, createAfterIssueId: anchorId }
  }

  // A stale/missing anchor (or an explicit end choice) is projected to the end.
  projected.push(proposed)
  return { orderedIssues: projected, targetIssue: proposed, createAfterIssueId: null }
}

/** Fingerprint of the exact pre-mutation state the reader reviewed. */
function correctionVersion(
  projection: ProjectedCorrection,
  targetNumber: string,
  insertPosition: string,
): string {
  return JSON.stringify({
    target: targetNumber,
    insertPosition,
    issues: projection.orderedIssues.map((issue) => [issue.id, issue.status]),
  })
}

interface IssueCorrectionDialogProps {
  isOpen: boolean
  threadId: number
  currentIssueNumber: string | null | undefined
  totalIssues: number | null | undefined
  threadTitle: string
  onClose: () => void
  /**
   * Called after the dialog applies a correction. `alreadyRefreshed` is true
   * when the correction came from an issue-card mutation that already
   * reconciled Roll/bootstrap caches, so callers can skip a duplicate fetch.
   */
  onSuccess: (options?: { alreadyRefreshed?: boolean }) => void
  /** Injectable issue-tracking API; defaults to the production issues service. */
  issuesApi?: IssueCorrectionIssuesApi
  dependenciesApi?: IssueCorrectionDependenciesApi
  cardsApi?: IssueCorrectionCardsApi
}

export default function IssueCorrectionDialog({
  isOpen,
  threadId,
  currentIssueNumber,
  totalIssues,
  threadTitle,
  onClose,
  onSuccess,
  issuesApi: issuesService = issuesApi,
  dependenciesApi: depsService = issueDependenciesApi,
  cardsApi: cardsService = issueCardsApi,
}: IssueCorrectionDialogProps) {
  const [selectedIssueNumber, setSelectedIssueNumber] = useState<string>('')
  const [isLoading, setIsLoading] = useState(false)
  const [isLoadingIssues, setIsLoadingIssues] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [allIssues, setAllIssues] = useState<Issue[]>([])
  const [hasLoadedOnce, setHasLoadedOnce] = useState(false)
  const [insertPosition, setInsertPosition] = useState<string>('end')
  const [preview, setPreview] = useState<{
    targetIssueNumber: string
    affected: Issue[]
    affectedIds: number[]
    affectedRatings: Record<number, number | null>
    willCompleteSeries: boolean
    dependentFrontier: string[]
    version: string
  } | null>(null)
  const [lastOperation, setLastOperation] = useState<IssueReadOperationResponse | null>(null)
  const [isUndoing, setIsUndoing] = useState(false)

  const hasNumericSelection = /^\d+$/.test(selectedIssueNumber.trim())
  // Only one exact owned canonical ID is safe. Repeated issue-number aliases
  // must be disambiguated by the correction UI rather than guessing artwork.
  const matchingIssues = allIssues.filter((issue) => issue.issue_number === selectedIssueNumber.trim())
  const selectedOwnedIssue = matchingIssues.length === 1 ? matchingIssues[0] : null

  const loadAllIssues = useCallback(async () => {
    const loadedIssues: Issue[] = []
    const seenPageTokens = new Set<string>()
    let nextPageToken: string | null = null

    while (true) {
      const params: IssueListParams = { page_size: 100 }
      if (nextPageToken) {
        params.page_token = nextPageToken
      }
      const data = await issuesService.list(threadId, params)

      if (!data.issues || data.issues.length === 0) {
        break
      }

      loadedIssues.push(...(data.issues || []))

      if (!data.next_page_token || seenPageTokens.has(data.next_page_token)) {
        break
      }

      seenPageTokens.add(data.next_page_token)
      nextPageToken = data.next_page_token
    }

    return loadedIssues
  }, [threadId, issuesService])

  const fetchIssues = useCallback(async (retryAttempt = 0) => {
    setIsLoadingIssues(true)
    setError(null)
    try {
      const loadedIssues = await loadAllIssues()

      setAllIssues(loadedIssues)
      if (!currentIssueNumber) {
        const firstUnreadIssue = loadedIssues.find((issue) => issue.status !== 'read')
        setSelectedIssueNumber(firstUnreadIssue?.issue_number ?? loadedIssues[0]?.issue_number ?? '')
      }
      setHasLoadedOnce(true)
    } catch (_err) {
      if (retryAttempt < 2) {
        await fetchIssues(retryAttempt + 1)
      } else {
        setError('Failed to load issues after multiple attempts. Please try again.')
      }
    } finally {
      setIsLoadingIssues(false)
    }
  }, [currentIssueNumber, loadAllIssues])

  useEffect(() => {
    if (isOpen) {
      setSelectedIssueNumber(currentIssueNumber ?? '')
      setInsertPosition('end')
      setPreview(null)
      setLastOperation(null)
      setError(null)
      fetchIssues()
      // Discover a persisted bulk operation so Undo survives reload/cross-tab.
      const discover = async () => {
        const getOperation = issuesService.getReadOperation
        if (!getOperation) return
        let receipt: ReturnType<typeof findBulkReadReceipt> = null
        try { receipt = findBulkReadReceipt(threadId) } catch { return }
        if (!receipt) return
        try {
          const op = await getOperation(receipt.operationId)
          if (!op.undone_at) setLastOperation(op)
          else clearBulkReadReceipt(threadId, receipt.operationId)
        } catch (error: unknown) {
          // A failed read does not prove the operation is unavailable to its owner.
          // Keep the receipt for recovery from Queue/History after reconnecting.
          if (getApiErrorStatus(error) !== 404) {
            setError('Could not load the previous bulk read. Its Undo receipt was kept for retry.')
          }
        }
      }
      void discover()
    }
  }, [isOpen, currentIssueNumber, fetchIssues, threadId, issuesService])

  // Preview state is not a stable callback dependency, so the reviewed ids and
  // version are passed explicitly. Both are validated against freshly loaded
  // pre-mutation state BEFORE any create/move/write (#4655 review F3/R3).
  const applyCorrection = useCallback(async (reviewed?: ReviewedCorrection) => {
    const targetNumber = selectedIssueNumber.trim()
    if (!targetNumber) {
      setError('Please enter an issue identifier')
      return
    }

    setIsLoading(true)
    setError(null)

    try {
      const projection = projectCorrection(await loadAllIssues(), targetNumber, insertPosition)
      const version = correctionVersion(projection, targetNumber, insertPosition)
      const targetIndex = projection.orderedIssues.findIndex(
        (issue) => issue.id === projection.targetIssue.id,
      )
      const unreadBeforeTarget = (targetIndex === -1 ? [] : projection.orderedIssues.slice(0, targetIndex))
        .filter((issue) => issue.status !== 'read')

      if (
        reviewed &&
        (reviewed.version !== version ||
          reviewed.ids.join(',') !== unreadBeforeTarget.map((issue) => issue.id).join(','))
      ) {
        setError('Issues changed since review. Please review changes again.')
        return
      }

      let targetIssue = projection.targetIssue
      if (targetIssue.id === -1) {
        const createdIssues = await issuesService.create(threadId, targetNumber, {
          insert_after_issue_id: projection.createAfterIssueId,
        })
        const createdTarget = createdIssues.issues.find(
          (issue) => issue.issue_number === targetNumber,
        )
        if (!createdTarget) {
          throw new Error('Created issue was not returned by the API')
        }
        targetIssue = createdTarget
        if (insertPosition === 'start') {
          await issuesService.move(targetIssue.id, null)
        }
      }

      // Bind the bulk write to the reviewed projection; do not recompute the
      // affected set after the create shifted rows around.
      let operation: IssueReadOperationResponse | null = null
      if (unreadBeforeTarget.length > 0) {
        operation = await issuesService.bulkMarkRead(unreadBeforeTarget.map((issue) => issue.id))
      }

      if (targetIssue.status === 'read') {
        await issuesService.markUnread(targetIssue.id)
      }

      setLastOperation(operation)
      if (operation) {
        try { writeBulkReadReceipt(threadId, operation.id) } catch { /* ignore */ }
      }
      setPreview(null)
      onSuccess()
      if (!operation) onClose()
    } catch (_err) {
      setError('Failed to update issue. Please try again.')
    } finally {
      setIsLoading(false)
    }
  }, [selectedIssueNumber, insertPosition, threadId, loadAllIssues, issuesService, onSuccess, onClose])


  const buildPreview = useCallback(async () => {
    const targetNumber = selectedIssueNumber.trim()
    if (!targetNumber) {
      setError('Please enter an issue identifier')
      return
    }

    setIsLoading(true)
    setError(null)
    try {
      const projection = projectCorrection(await loadAllIssues(), targetNumber, insertPosition)
      const projectedIssues = projection.orderedIssues
      const targetIssue = projection.targetIssue
      const targetIndex = projectedIssues.findIndex((issue) => issue.id === targetIssue.id)
      const unreadBeforeTarget = (targetIndex === -1 ? [] : projectedIssues.slice(0, targetIndex))
        .filter((issue) => issue.status !== 'read')

      // Read state alone cannot distinguish marked read from read & rated, so
      // fetch the affected ratings in one bounded batch for the review panel.
      let affectedRatings: Record<number, number | null> = {}
      if (unreadBeforeTarget.length > 0) {
        try {
          const cards = await cardsService.fetchCards(unreadBeforeTarget.map((issue) => issue.id))
          affectedRatings = Object.fromEntries(
            cards.map((card) => [card.issue_id, card.rating ?? null]),
          )
        } catch {
          // Best-effort preview: ratings are explanatory, not authorization.
        }
      }

      let dependentFrontier: string[] = []
      try {
        const deps = await depsService.listForThread(threadId)
        const affectedIds = new Set(unreadBeforeTarget.map((i) => i.id))
        const frontier = new Set<string>()
        for (const issueDep of deps.issues ?? []) {
          if (!affectedIds.has(issueDep.issue_id)) continue
          // Outgoing edges point at the dependent issue. Despite their legacy
          // `source_*` wire names, those fields describe the TARGET for an
          // outgoing edge, including targets in another series (#4655 R4).
          for (const edge of issueDep.outgoing ?? []) {
            const issueLabel = edge.source_issue_number ?? String(edge.source_issue_id ?? '?')
            frontier.add(
              edge.source_thread_title
                ? `${edge.source_thread_title} #${issueLabel}`
                : `#${issueLabel}`,
            )
          }
        }
        dependentFrontier = Array.from(frontier)
      } catch {
        // best-effort preview
      }

      // Project the FINAL state, including the target: applyCorrection always
      // leaves the target unread, so it keeps the series active (#4655 R4).
      const finalStatus = (issue: Issue): string => {
        if (issue.id === targetIssue.id) return 'unread'
        if (unreadBeforeTarget.some((unread) => unread.id === issue.id)) return 'read'
        return issue.status
      }
      const willCompleteSeries = projectedIssues.length > 0
        && projectedIssues.every((issue) => finalStatus(issue) === 'read')

      // Always present the review step, even when no issue is about to be bulk
      // read: creating or moving the target is itself a correction the reader
      // must be able to cancel after seeing the projected completion effects.
      setPreview({
        targetIssueNumber: targetNumber,
        affected: unreadBeforeTarget,
        affectedIds: unreadBeforeTarget.map((i) => i.id),
        affectedRatings,
        willCompleteSeries,
        dependentFrontier,
        version: correctionVersion(projection, targetNumber, insertPosition),
      })
    } catch {
      setError('Failed to prepare issue correction preview. Please try again.')
    } finally {
      setIsLoading(false)
    }
  }, [selectedIssueNumber, insertPosition, threadId, loadAllIssues, depsService, cardsService])


  const handleSubmit = useCallback(async () => {
    if (preview) {
      await applyCorrection({ ids: preview.affectedIds, version: preview.version })
      return
    }
    await buildPreview()
  }, [preview, applyCorrection, buildPreview])


  const handleUndo = useCallback(async () => {
    if (!lastOperation) return
    setIsUndoing(true)
    setError(null)
    try {
      const undoOperation = issuesService.undoReadOperation
      let undoResponse: IssueReadOperationUndoResponse | null = null
      if (undoOperation) {
        undoResponse = await undoOperation(lastOperation.id)
      } else {
        undoResponse = await issuesApi.undoReadOperation(lastOperation.id)
      }
      try { clearBulkReadReceipt(threadId, lastOperation.id) } catch { /* ignore */ }
      if (undoResponse && undoResponse.skipped_issue_ids.length > 0) {
        setError(`Undo skipped ${undoResponse.skipped_issue_ids.length} issue(s) changed later.`)
      }
      setLastOperation(null)
      setPreview(null)
      onSuccess()
      onClose()
    } catch {
      setError('Failed to undo bulk read operation. Please try again.')
    } finally {
      setIsUndoing(false)
    }
  }, [lastOperation, issuesService, onSuccess, onClose, threadId])

  const adjustIssue = useCallback((delta: number) => {
    const currentValue = selectedIssueNumber

    if (!currentValue || !/^\d+$/.test(currentValue)) {
      setError('Use the text field for annuals or specials')
      return
    }

    const current = parseInt(currentValue, 10)

    if (isNaN(current)) {
      setError('Invalid issue number')
      return
    }

    const newNum = current + delta
    const min = 1
    const max = totalIssues !== null && totalIssues !== undefined ? totalIssues : 999

    if (newNum >= min && newNum <= max) {
      setSelectedIssueNumber(newNum.toString())
      setError(null)
    }
  }, [selectedIssueNumber, totalIssues])

  const handleKeyDown = useCallback((e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      handleSubmit()
    }
  }, [handleSubmit])

  if (!isOpen) return null

  return (
    <Modal
      isOpen={isOpen}
      title="Fix Issue Number"
      onClose={onClose}
      data-testid="issue-correction-dialog"
    >
      <div className="space-y-4">
        <p className="text-sm text-stone-400">
          Reading: <span className="text-stone-200 font-bold">{threadTitle}</span>
        </p>

        {isLoadingIssues ? (
          <div className="bg-amber-600/10 border border-amber-600/20 rounded-lg p-6 text-center">
            <p className="text-sm text-stone-400">Loading issues...</p>
          </div>
        ) : (
          <div className="bg-amber-600/10 border border-amber-600/20 rounded-lg p-4">
            <label htmlFor="issue-number" className="block text-sm font-bold text-stone-300 mb-2">
              What issue are you currently on?
            </label>

            <div className="flex items-center justify-center gap-4">
              <button
                type="button"
                onClick={() => adjustIssue(-1)}
                disabled={isLoading || !hasNumericSelection}
                className="w-14 h-14 flex items-center justify-center bg-white/5 hover:bg-white/10 border border-white/10 rounded-xl text-2xl font-bold text-stone-200 transition-all disabled:opacity-50 active:scale-95 focus:ring-2 focus:ring-amber-500"
                aria-label="Decrease issue number"
              >
                −
              </button>

              <div className="flex-1 text-center">
                <input
                  id="issue-number"
                  type="text"
                  inputMode="text"
                  maxLength={50}
                  value={selectedIssueNumber}
                  onChange={(e) => {
                    setSelectedIssueNumber(e.target.value)
                    setError(null)
                  }}
                  onKeyDown={handleKeyDown}
                  disabled={isLoading}
                  className="w-full text-center text-3xl font-black rounded-lg py-3 px-4 form-control"
                  aria-describedby="issue-range"
                />
                {totalIssues && (
                  <p id="issue-range" className="text-xs text-stone-500 mt-1">
                    of {totalIssues}
                  </p>
                )}
              </div>

              <button
                type="button"
                onClick={() => adjustIssue(1)}
                disabled={isLoading || !hasNumericSelection}
                className="w-14 h-14 flex items-center justify-center bg-white/5 hover:bg-white/10 border border-white/10 rounded-xl text-2xl font-bold text-stone-200 transition-all disabled:opacity-50 active:scale-95 focus:ring-2 focus:ring-amber-500"
                aria-label="Increase issue number"
              >
                +
              </button>
            </div>
            {selectedOwnedIssue && (
              <div className="mt-3">
                <CompactIssueCardTrigger
                  issueId={selectedOwnedIssue.id}
                  threadTitle={threadTitle}
                  issueNumber={selectedOwnedIssue.issue_number}
                  status={selectedOwnedIssue.status === 'read' ? 'read' : 'unread'}
                  onMutated={() => {
                    void fetchIssues()
                    onSuccess({ alreadyRefreshed: true })
                  }}
                />
              </div>
            )}
            {!allIssues.some((issue) => issue.issue_number === selectedIssueNumber.trim()) && (
              <div className="mt-4">
                <label htmlFor="issue-position" className="block text-xs font-bold text-stone-400 mb-2">
                  Place new issue
                </label>
                <select
                  id="issue-position"
                  value={insertPosition}
                  onChange={(event) => setInsertPosition(event.target.value)}
                  disabled={isLoading}
                  className="w-full rounded-lg py-2 px-3 text-sm form-control"
                >
                  <option value="end">At the end</option>
                  <option value="start">At the beginning</option>
                  {allIssues.map((issue) => (
                    <option key={issue.id} value={issue.id}>
                      After {issue.issue_number}
                    </option>
                  ))}
                </select>
              </div>
            )}
          </div>
        )}

        {preview && (
          <div className="rounded-lg border border-amber-600/30 bg-amber-600/10 p-3 space-y-2" data-testid="bulk-read-preview">
            <p className="text-sm font-bold text-stone-200">Review bulk read changes</p>
            <p className="text-xs text-stone-400">
              Marking {preview.affected.length} issue{preview.affected.length === 1 ? '' : 's'} as read before #{preview.targetIssueNumber}.
            </p>
            <ul className="text-xs text-stone-300 space-y-1 max-h-32 overflow-auto">
              {preview.affected.map((issue) => (
                <li key={issue.id}>
                  #{issue.issue_number} — current: {issue.status}
                  {preview.affectedRatings[issue.id] != null
                    ? ` · rated ${preview.affectedRatings[issue.id]?.toFixed(1)}`
                    : ' · no rating'}
                </li>
              ))}
            </ul>
            <p className="text-xs text-stone-400">
              {preview.willCompleteSeries
                ? 'Series completion effect: this will complete the series and remove it from the active Queue.'
                : 'Series completion effect: series will remain active.'}
            </p>
            <p className="text-xs text-stone-400">
              Dependent frontier: {preview.dependentFrontier.length > 0 ? preview.dependentFrontier.join(', ') : 'no direct dependent issues detected in this series.'}
            </p>
            <p className="text-xs text-stone-500">
              Read states explained: marked read = read without rating; read &amp; rated = read with rating; still unread = not read.
            </p>
          </div>
        )}

        {lastOperation && (
          <div className="rounded-lg border border-green-600/30 bg-green-600/10 p-3 space-y-2" data-testid="bulk-read-review">
            <p className="text-sm font-bold text-stone-200">Bulk read applied</p>
            <p className="text-xs text-stone-400">
              Operation #{lastOperation.id} recorded {lastOperation.items.length} issue changes. You can review or undo this exact operation.
            </p>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => void handleUndo()}
                disabled={isUndoing}
                className="py-2 px-3 bg-white/5 hover:bg-white/10 border border-white/10 rounded-lg text-xs font-bold uppercase tracking-wider transition-all disabled:opacity-50"
              >
                {isUndoing ? 'Undoing...' : 'Undo'}
              </button>
            </div>
          </div>
        )}

        {error && (
          <div className="p-3 bg-red-800/20 border border-red-800/50 rounded-lg">
            <p className="text-sm text-red-400 text-center mb-2">{error}</p>
            {!isLoadingIssues && !hasLoadedOnce && (
              <button
                type="button"
                onClick={() => fetchIssues()}
                className="w-full py-2 bg-red-800/40 hover:bg-red-800/60 border border-red-800/60 rounded text-xs font-bold uppercase tracking-wider transition-all"
              >
                Retry
              </button>
            )}
          </div>
        )}

        <div className="flex gap-3">
          <button
            type="button"
            onClick={() => {
              if (preview) { setPreview(null); return }
              onClose()
            }}
            disabled={isLoading || isUndoing}
            className="flex-1 py-3 bg-white/5 hover:bg-white/10 border border-white/10 rounded-xl text-sm font-black uppercase tracking-wider transition-all disabled:opacity-50"
          >
            {preview ? 'Back' : 'Cancel'}
          </button>
          {!lastOperation ? (
            <button
              type="button"
              onClick={() => void handleSubmit()}
              disabled={isLoading}
              className="flex-1 py-3 bg-amber-600/20 hover:bg-amber-600/30 border border-amber-600/50 rounded-xl text-sm font-black uppercase tracking-wider transition-all disabled:opacity-50"
            >
              {isLoading ? 'Working...' : preview ? 'Confirm bulk read' : 'Review changes'}
            </button>
          ) : (
            <button
              type="button"
              onClick={onClose}
              className="flex-1 py-3 bg-amber-600/20 hover:bg-amber-600/30 border border-amber-600/50 rounded-xl text-sm font-black uppercase tracking-wider transition-all"
            >
              Done
            </button>
          )}
        </div>
      </div>
    </Modal>
  )
}
