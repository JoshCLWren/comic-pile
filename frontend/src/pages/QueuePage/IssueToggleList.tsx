import { useState, useEffect, useCallback, useRef } from 'react'
import type { DragEvent } from 'react'
import type { Issue, IssueDependenciesResponse } from '../../types'
import { issuesApi } from '../../services/api-issues'
import { dependenciesApi } from '../../services/api'
import { getApiErrorDetail } from '../../utils/apiError'
import Tooltip from '../../components/Tooltip'
import Modal from '../../components/Modal'
import { getDependencyTooltip } from '../../utils/dependencyHelpers'
import {
  reorderIssuesForDrop,
  moveIssueByStep,
  normalizeIssueOrder,
  applyIssueMutation,
  applyIssueMutations,
  getPendingIssueIds,
} from './issueUtils'
import type { IssueMutation, QueuedIssueMutation } from './types'

export function IssueToggleList({ threadId }: {
  threadId: number
}) {
  const [issues, setIssues] = useState<Issue[]>([])
  const [isLoading, setIsLoading] = useState(true)
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
  const baseIssuesRef = useRef<Issue[]>([])
  const pendingMutationsRef = useRef<IssueMutation[]>([])
  const isProcessingMutationsRef = useRef(false)
  const nextMutationIdRef = useRef(1)

  const getNextUnreadIssueId = useCallback(() => {
    return issues.find((issue) => issue.status === 'unread')?.id ?? null
  }, [issues])

  const getVisibilityWindow = useCallback((issueList: Issue[], nextUnreadId: number | null) => {
    if (!nextUnreadId) {
      return { startIndex: issueList.length - 3, endIndex: issueList.length }
    }

    const nextUnreadIndex = issueList.findIndex((issue) => issue.id === nextUnreadId)
    if (nextUnreadIndex === -1) {
      return { startIndex: issueList.length - 3, endIndex: issueList.length }
    }

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

  const syncOptimisticIssues = useCallback((baseIssues: Issue[], pendingMutations: IssueMutation[]) => {
    setIssues(applyIssueMutations(baseIssues, pendingMutations))
    setToggling(getPendingIssueIds(pendingMutations, 'toggle'))
    setDeleting(getPendingIssueIds(pendingMutations, 'delete'))
  }, [])

  const fetchAllIssues = useCallback(async (): Promise<Issue[]> => {
    const allIssues: Issue[] = []
    const seenPageTokens = new Set<string>()
    let nextPageToken: string | null = null

    while (true) {
      const data = await issuesApi.list(threadId, {
        page_size: 100,
        ...(nextPageToken ? { page_token: nextPageToken } : {}),
      })
      allIssues.push(...(data.issues || []))

      if (!data.next_page_token || seenPageTokens.has(data.next_page_token)) {
        return allIssues
      }

      seenPageTokens.add(data.next_page_token)
      nextPageToken = data.next_page_token
    }
  }, [threadId])

  const fetchDependencies = useCallback(async (issueList: Issue[]) => {
    const depsMap: Record<number, IssueDependenciesResponse> = {}
    await Promise.all(
      issueList.map(async (issue) => {
        try {
          const deps = await dependenciesApi.getIssueDependencies(issue.id)
          if (deps.incoming.length > 0 || deps.outgoing.length > 0) {
            depsMap[issue.id] = deps
          }
        } catch (error) {
          console.error(`Failed to load dependencies for issue ${issue.id}:`, error)
        }
      })
    )
    setDependencies(depsMap)
  }, [])

  const focusMoveControl = useCallback((issueId: number, direction: 'up' | 'down') => {
    const focusTarget = () => {
      document
        .querySelector<HTMLButtonElement>(`[data-move-control="${direction}-${issueId}"]`)
        ?.focus()
    }

    if (typeof window !== 'undefined' && typeof window.requestAnimationFrame === 'function') {
      window.requestAnimationFrame(focusTarget)
      return
    }

    setTimeout(focusTarget, 0)
  }, [])

  const runIssueMutation = useCallback(async (mutation: IssueMutation) => {
    switch (mutation.type) {
      case 'toggle':
        if (mutation.nextStatus === 'read') {
          await issuesApi.markRead(mutation.issueId)
        } else {
          await issuesApi.markUnread(mutation.issueId)
        }
        return
      case 'delete':
        await issuesApi.delete(mutation.issueId)
        return
      case 'reorder':
        await issuesApi.reorder(threadId, normalizeIssueOrder(baseIssuesRef.current, mutation.issueIds))
    }
  }, [threadId])

  const processIssueMutations = useCallback(async () => {
    if (isProcessingMutationsRef.current) {
      return
    }

    isProcessingMutationsRef.current = true

    try {
      while (pendingMutationsRef.current.length > 0) {
        const currentMutation = pendingMutationsRef.current[0]
        if (!currentMutation) {
          break
        }

        try {
          await runIssueMutation(currentMutation)
          baseIssuesRef.current = applyIssueMutation(baseIssuesRef.current, currentMutation)
        } catch (err: unknown) {
          try {
            baseIssuesRef.current = await fetchAllIssues()
          } catch (refreshErr) {
            console.error('[IssueToggleList] Error refetching issues after mutation failure:', refreshErr)
          }
          setActionError(getApiErrorDetail(err))
        } finally {
          pendingMutationsRef.current = pendingMutationsRef.current.filter(
            (mutation) => mutation.id !== currentMutation.id
          )
          syncOptimisticIssues(baseIssuesRef.current, pendingMutationsRef.current)
        }
      }
    } finally {
      isProcessingMutationsRef.current = false
    }
  }, [fetchAllIssues, runIssueMutation, syncOptimisticIssues])

  const enqueueIssueMutation = useCallback((mutation: QueuedIssueMutation) => {
    const queuedMutation = {
      ...mutation,
      id: nextMutationIdRef.current++,
    } as IssueMutation

    pendingMutationsRef.current = [...pendingMutationsRef.current, queuedMutation]
    syncOptimisticIssues(baseIssuesRef.current, pendingMutationsRef.current)
    void processIssueMutations()
  }, [processIssueMutations, syncOptimisticIssues])

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

  const loadIssues = useCallback(async () => {
    setIsLoading(true)
    try {
      baseIssuesRef.current = await fetchAllIssues()
      syncOptimisticIssues(baseIssuesRef.current, pendingMutationsRef.current)
      await fetchDependencies(baseIssuesRef.current)
    } catch {
      // Non-critical
    } finally {
      setIsLoading(false)
    }
  }, [fetchAllIssues, fetchDependencies, syncOptimisticIssues])

  useEffect(() => {
    loadIssues()
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
    if (!addRange.trim()) {
      return
    }
    setIsAdding(true)
    setAddError(null)
    try {
      await issuesApi.create(threadId, addRange.trim())
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

    if (nextIssues === issues) {
      return
    }

    enqueueIssueReorder(nextIssues)
  }

  const handleDragEnd = () => {
    setDraggedIssueId(null)
    setDragOverIssueId(null)
  }

  function handleDeleteIssue(issue: Issue) {
    if (!window.confirm(`Delete issue #${issue.issue_number}?`)) {
      return
    }

    setActionError(null)
    enqueueIssueMutation({
      type: 'delete',
      issueId: issue.id,
    })
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

    if (!isExpanded) {
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

  const visibleIssues = getVisibleIssues()
  const hasHiddenIssues = issues.length > 5 && !isExpanded

  return (
    <div className="space-y-2">
      <div className="flex justify-between items-center">
        <p className="text-[10px] font-bold uppercase tracking-widest text-stone-500">Issues</p>
        {issues.length > 5 && (
          <button
            type="button"
            onClick={() => setIsExpanded(!isExpanded)}
            className="text-[10px] font-black uppercase tracking-widest text-amber-400 hover:text-amber-300 transition-colors"
          >
            {isExpanded ? 'Show fewer' : `Show all ${issues.length}`}
          </button>
        )}
      </div>
      <p className="sr-only" aria-live="polite">{reorderAnnouncement}</p>
      {hasHiddenIssues && (
        <p className="text-xs text-stone-500 italic">
          Showing {visibleIssues.length} of {issues.length} issues around your current position
        </p>
      )}
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
                  'px-2 py-0.5 text-xs font-bold transition-all',
                  isBusy ? '' : 'hover:opacity-80 cursor-grab active:cursor-grabbing',
                ].join(' ')}
                title={`#${issue.issue_number}: ${issue.status}. Drag to reorder.`}
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
                      className="dependency-indicator min-h-[44px] min-w-[44px] px-1 text-[10px] opacity-70 hover:opacity-100 cursor-help"
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
              <div className="flex border-l border-white/10">
                <button
                  type="button"
                  onClick={() => handleMoveIssue(issue, 'up')}
                  disabled={isBusy || !canMoveUp}
                  className={[
                    'h-7 w-7 text-[11px] font-black text-stone-500 transition-colors',
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
                    'h-7 w-7 text-[11px] font-black text-stone-500 transition-colors',
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
                  'pr-2 text-[10px] font-black text-stone-500 transition-colors',
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
      <div className="flex gap-2">
        <input
          type="text"
          value={addRange}
          onChange={(e) => setAddRange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              e.stopPropagation()
              void handleAddIssues()
            }
          }}
          placeholder="Add issues: 19-24 or 0, Annual 1"
          className="flex-1 bg-white/5 border border-white/10 rounded-lg px-2 py-1 text-xs text-stone-300"
          data-testid="issue-add-input"
        />
        <button
          type="button"
          onClick={() => handleAddIssues()}
          disabled={isAdding || !addRange.trim()}
          className="px-3 py-1 bg-white/5 border border-white/10 rounded-lg text-xs font-bold text-stone-300 hover:bg-white/10 disabled:opacity-50"
          data-testid="issue-add-button"
        >
          {isAdding ? '…' : 'Add'}
        </button>
      </div>
      {addError && (
        <p className="text-xs text-red-400">{addError}</p>
      )}
      {actionError && (
        <p className="text-xs text-red-400">{actionError}</p>
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
          </div>
        </Modal>
      )}
    </div>
  )
}
