import { useState, useEffect, useCallback, useRef } from 'react'
import type { ChangeEvent, DragEvent, FormEvent, MouseEvent, KeyboardEvent } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import Modal from '../components/Modal'
import PositionSlider from '../components/PositionSlider'
import Tooltip from '../components/Tooltip'
import LoadingSpinner from '../components/LoadingSpinner'
import DependencyBuilder from '../components/DependencyBuilder'
import MigrationDialog from '../components/MigrationDialog'
import { useMoveToBack, useMoveToFront, useMoveToPosition } from '../hooks/useQueue'
import {
  useCreateThread,
  useDeleteThread,
  useReactivateThread,
  useThreads,
  useUpdateThread,
} from '../hooks/useThread'
import { useSession } from '../hooks/useSession'
import { useSnooze, useUnsnooze } from '../hooks/useSnooze'
import { dependenciesApi, threadsApi } from '../services/api'
import { issuesApi } from '../services/api-issues'
import { useCollections } from '../contexts/CollectionContext'
import type { Issue, Thread } from '../types'
import { getApiErrorDetail } from '../utils/apiError'

const FORMAT_OPTIONS = ['Comics', 'Manga', 'Trade Paperback', 'Graphic Novel', 'Other'] as const

/**
 * Badge component displaying collection name for a thread.
 */
function CollectionBadge({ collectionId }: { collectionId: number }) {
  const { collections } = useCollections()
  const collection = collections.find(c => c.id === collectionId)

  if (!collection) return null

  return (
    <span data-testid="collection-badge" className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-amber-500/20 text-amber-300 border border-amber-500/30">
      {collection.name}
    </span>
  )
}

/**
 * Dropdown select for format field. If the current value doesn't match
 * any preset, it's added as an extra option so it isn't lost.
 */
function FormatSelect({ value, onChange, required }: {
  value: string
  onChange: (value: string) => void
  required?: boolean
}) {
  const hasCustom = value && !FORMAT_OPTIONS.includes(value as typeof FORMAT_OPTIONS[number])

  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="w-full bg-white/5 border border-white/10 rounded-xl px-3 py-2 text-sm text-stone-300"
      required={required}
    >
      <option value="">Select format...</option>
      {hasCustom && <option value={value}>{value}</option>}
      {FORMAT_OPTIONS.map((fmt) => (
        <option key={fmt} value={fmt}>{fmt}</option>
      ))}
    </select>
  )
}

/**
 * Inline issue list for migrated threads in the edit modal.
 */
function reorderIssuesForDrop(
  issues: Issue[],
  draggedIssueId: number,
  targetIssueId: number
): Issue[] {
  const draggedIndex = issues.findIndex((issue) => issue.id === draggedIssueId)
  const targetIndex = issues.findIndex((issue) => issue.id === targetIssueId)

  if (draggedIndex === -1 || targetIndex === -1 || draggedIndex === targetIndex) {
    return issues
  }

  const nextIssues = [...issues]
  const draggedIssue = nextIssues.splice(draggedIndex, 1)[0]
  if (!draggedIssue) {
    return issues
  }
  const targetIndexAfterRemoval = nextIssues.findIndex((issue) => issue.id === targetIssueId)
  if (targetIndexAfterRemoval === -1) {
    return issues
  }
  nextIssues.splice(targetIndexAfterRemoval + 1, 0, draggedIssue)
  return nextIssues
}

type IssueMutation =
  | { id: number; type: 'delete'; issueId: number }
  | { id: number; type: 'reorder'; issueIds: number[] }
  | { id: number; type: 'toggle'; issueId: number; nextStatus: Issue['status'] }

type QueuedIssueMutation =
  | { type: 'delete'; issueId: number }
  | { type: 'reorder'; issueIds: number[] }
  | { type: 'toggle'; issueId: number; nextStatus: Issue['status'] }

function normalizeIssueOrder(issues: Issue[], issueIds: number[]): number[] {
  const existingIssueIds = new Set(issues.map((issue) => issue.id))
  const normalizedIssueIds: number[] = []
  const seenIssueIds = new Set<number>()

  for (const issueId of issueIds) {
    if (!existingIssueIds.has(issueId) || seenIssueIds.has(issueId)) {
      continue
    }
    normalizedIssueIds.push(issueId)
    seenIssueIds.add(issueId)
  }

  for (const issue of issues) {
    if (!seenIssueIds.has(issue.id)) {
      normalizedIssueIds.push(issue.id)
    }
  }

  return normalizedIssueIds
}

function applyIssueMutation(issues: Issue[], mutation: IssueMutation): Issue[] {
  switch (mutation.type) {
    case 'toggle':
      return issues.map((issue) => (
        issue.id === mutation.issueId
          ? {
              ...issue,
              status: mutation.nextStatus,
              read_at: mutation.nextStatus === 'read' ? new Date().toISOString() : null,
            }
          : issue
      ))
    case 'delete':
      return issues.filter((issue) => issue.id !== mutation.issueId)
    case 'reorder': {
      const normalizedIssueIds = normalizeIssueOrder(issues, mutation.issueIds)
      const issueMap = new Map(issues.map((issue) => [issue.id, issue]))
      return normalizedIssueIds
        .map((issueId) => issueMap.get(issueId))
        .filter((issue): issue is Issue => issue !== undefined)
    }
  }
}

function applyIssueMutations(issues: Issue[], mutations: IssueMutation[]): Issue[] {
  return mutations.reduce((currentIssues, mutation) => applyIssueMutation(currentIssues, mutation), issues)
}

function getPendingIssueIds(mutations: IssueMutation[], type: 'delete' | 'toggle'): Set<number> {
  const pendingIssueIds = new Set<number>()

  for (const mutation of mutations) {
    if (mutation.type === type) {
      pendingIssueIds.add(mutation.issueId)
    }
  }

  return pendingIssueIds
}

export function IssueToggleList({ threadId }: {
  threadId: number
}) {
  const [issues, setIssues] = useState<Issue[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [addRange, setAddRange] = useState('')
  const [isAdding, setIsAdding] = useState(false)
  const [addError, setAddError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [toggling, setToggling] = useState<Set<number>>(new Set())
  const [deleting, setDeleting] = useState<Set<number>>(new Set())
  const [draggedIssueId, setDraggedIssueId] = useState<number | null>(null)
  const [dragOverIssueId, setDragOverIssueId] = useState<number | null>(null)
  const baseIssuesRef = useRef<Issue[]>([])
  const pendingMutationsRef = useRef<IssueMutation[]>([])
  const isProcessingMutationsRef = useRef(false)
  const nextMutationIdRef = useRef(1)

  const syncOptimisticIssues = useCallback((baseIssues: Issue[], pendingMutations: IssueMutation[]) => {
    setIssues(applyIssueMutations(baseIssues, pendingMutations))
    setToggling(getPendingIssueIds(pendingMutations, 'toggle'))
    setDeleting(getPendingIssueIds(pendingMutations, 'delete'))
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
  }, [runIssueMutation, syncOptimisticIssues])

  const enqueueIssueMutation = useCallback((mutation: QueuedIssueMutation) => {
    const queuedMutation = {
      ...mutation,
      id: nextMutationIdRef.current++,
    } as IssueMutation

    pendingMutationsRef.current = [...pendingMutationsRef.current, queuedMutation]
    syncOptimisticIssues(baseIssuesRef.current, pendingMutationsRef.current)
    void processIssueMutations()
  }, [processIssueMutations, syncOptimisticIssues])

  const loadIssues = useCallback(async () => {
    setIsLoading(true)
    try {
      // Load all issues (use large page size)
      const data = await issuesApi.list(threadId, { page_size: 100 })
      baseIssuesRef.current = data.issues || []
      syncOptimisticIssues(baseIssuesRef.current, pendingMutationsRef.current)
    } catch {
      // Non-critical
    } finally {
      setIsLoading(false)
    }
  }, [syncOptimisticIssues, threadId])

  useEffect(() => {
    loadIssues()
  }, [loadIssues])

  async function handleToggle(issue: Issue) {
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

  const handleDrop = (targetIssueId: number) => async (event: DragEvent<HTMLDivElement>) => {
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

    const nextIssueIds = nextIssues.map((issue) => issue.id)
    const currentIssueIds = issues.map((issue) => issue.id)
    const orderDidChange = nextIssueIds.some((issueId, index) => issueId !== currentIssueIds[index])

    if (!orderDidChange) {
      return
    }

    setActionError(null)
    enqueueIssueMutation({
      type: 'reorder',
      issueIds: nextIssueIds,
    })
  }

  const handleDragEnd = () => {
    setDraggedIssueId(null)
    setDragOverIssueId(null)
  }

  async function handleDeleteIssue(issue: Issue) {
    if (!window.confirm(`Delete issue #${issue.issue_number}?`)) {
      return
    }

    setActionError(null)
    enqueueIssueMutation({
      type: 'delete',
      issueId: issue.id,
    })
  }

  if (isLoading) return <p className="text-xs text-stone-500">Loading issues…</p>

  return (
    <div className="space-y-2">
      <p className="text-[10px] font-bold uppercase tracking-widest text-stone-500">Issues</p>
      <div className="flex flex-wrap gap-1 max-h-40 overflow-auto">
        {issues.map((issue) => {
          const isBusy = toggling.has(issue.id) || deleting.has(issue.id)
          const isDragOver = dragOverIssueId === issue.id
          const isDragged = draggedIssueId === issue.id

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
    </div>
  )
}

const DEFAULT_CREATE_STATE = {
  title: '',
  format: 'Comics',
  issuesRemaining: 1,
  notes: '',
  issues: '',
  trackingMode: 'simple' as 'simple' | 'tracked',
  lastIssueRead: 0,
}

type QueueFormState = typeof DEFAULT_CREATE_STATE

export default function QueuePage() {
  const navigate = useNavigate()
  const location = useLocation()
  const { activeCollectionId } = useCollections()
  const { data: threads, isPending, refetch } = useThreads('', activeCollectionId)
  const { data: session, refetch: refetchSession } = useSession()
  const createMutation = useCreateThread()
  const updateMutation = useUpdateThread()
  const deleteMutation = useDeleteThread()
  const reactivateMutation = useReactivateThread()
  const moveToFrontMutation = useMoveToFront()
  const moveToBackMutation = useMoveToBack()
  const moveToPositionMutation = useMoveToPosition()
  const snoozeMutation = useSnooze()
  const unsnoozeMutation = useUnsnooze()

  const [isCreateOpen, setIsCreateOpen] = useState(false)
  const [isEditOpen, setIsEditOpen] = useState(false)
  const [isReactivateOpen, setIsReactivateOpen] = useState(false)
  const [createForm, setCreateForm] = useState<QueueFormState>(DEFAULT_CREATE_STATE)
  const [editForm, setEditForm] = useState<QueueFormState>(DEFAULT_CREATE_STATE)
  const [editingThread, setEditingThread] = useState<Thread | null>(null)
  const [reactivateThreadId, setReactivateThreadId] = useState('')
  const [issuesToAdd, setIssuesToAdd] = useState(1)
  const [draggedThreadId, setDraggedThreadId] = useState<number | null>(null)
  const [dragOverThreadId, setDragOverThreadId] = useState<number | null>(null)
  const [repositioningThread, setRepositioningThread] = useState<Thread | null>(null)
  const [reorderError, setReorderError] = useState<string | null>(null)
  const [selectedThread, setSelectedThread] = useState<Thread | null>(null)
  const [isActionSheetOpen, setIsActionSheetOpen] = useState(false)
  const [showMigrationDialog, setShowMigrationDialog] = useState(false)
  const [threadToMigrate, setThreadToMigrate] = useState<Thread | null>(null)
  const [blockedThreadIds, setBlockedThreadIds] = useState<number[]>([])
  const [blockingReasonMap, setBlockingReasonMap] = useState<Record<number, string[]>>({})
  const [dependencyThread, setDependencyThread] = useState<Thread | null>(null)
  const [isDependencyBuilderOpen, setIsDependencyBuilderOpen] = useState(false)
  const [issuePreview, setIssuePreview] = useState<number | null>(null)
  const [issueParseError, setIssueParseError] = useState<string | null>(null)

  useEffect(() => {
    if (location.state?.editThreadId && threads) {
      const thread = threads.find((t) => t.id === location.state.editThreadId)
      if (thread) {
        openEditModal(thread)
        navigate(location.pathname, { replace: true, state: {} })
      }
    }
  }, [location.state, location.pathname, threads, navigate])

  async function refreshBlockedState() {
    try {
      const blockedIds = await dependenciesApi.listBlockedThreadIds()
      setBlockedThreadIds(blockedIds)

      if (blockedIds.length === 0) {
        setBlockingReasonMap({})
        return
      }

      const details: Array<[number, string[]]> = await Promise.all(
        blockedIds.map(async (threadId) => {
            try {
              const info = await dependenciesApi.getBlockingInfo(threadId)
              return [threadId, info.blocking_reasons || []]
            } catch {
              return [threadId, []]
            }
          })
        )

      setBlockingReasonMap(Object.fromEntries(details))
    } catch {
      setBlockedThreadIds([])
      setBlockingReasonMap({})
    }
  }

  useEffect(() => {
    if (!threads) return
    refreshBlockedState()
  }, [threads])

  useEffect(() => {
    const calculatePreview = async () => {
      const issueInput = createForm.trackingMode === 'tracked' ? createForm.issues : ''
      if (issueInput) {
        try {
          const { parseIssueRange } = await import('../utils/issueParser')
          const total = parseIssueRange(issueInput)
          setIssuePreview(total)
          setIssueParseError(null)
        } catch (err) {
          setIssuePreview(null)
          setIssueParseError(err instanceof Error ? err.message : 'Invalid issue range')
        }
      } else {
        setIssuePreview(null)
        setIssueParseError(null)
      }
    }

    calculatePreview()
  }, [createForm.issues, createForm.trackingMode])

  const activeThreads = threads
    ?.filter((thread) => thread.status === 'active')
    .sort((a, b) => a.queue_position - b.queue_position) ?? []
  const completedThreads = threads?.filter((thread) => thread.status === 'completed') ?? []

  const handleDelete = (threadId: number) => {
    if (window.confirm('Are you sure you want to delete this thread?')) {
      deleteMutation.mutate(threadId).then(() => refetch()).catch((err: unknown) => {
        alert(`Failed to delete thread: ${getApiErrorDetail(err)}`)
      })
    }
  }

  const handleMoveToFront = (threadId: number) => {
    moveToFrontMutation.mutate(threadId).then(() => refetch()).catch(() => {
      alert('Failed to move thread to front. Please try again.')
    })
  }

  const handleMoveToBack = (threadId: number) => {
    moveToBackMutation.mutate(threadId).then(() => refetch()).catch(() => {
      alert('Failed to move thread to back. Please try again.')
    })
  }

  const handleDragStart = (threadId: number) => (event: DragEvent<HTMLElement>) => {
    event.dataTransfer.effectAllowed = 'move'
    event.dataTransfer.setData('text/plain', String(threadId))
    setDraggedThreadId(threadId)
    setReorderError(null)
  }

  const handleDragOver = (threadId: number) => (event: DragEvent<HTMLElement>) => {
    event.preventDefault()
    setDragOverThreadId(threadId)
  }

  const handleDrop = (threadId: number) => (event: DragEvent<HTMLElement>) => {
    event.preventDefault()

    if (!draggedThreadId || draggedThreadId === threadId) {
      setDragOverThreadId(null)
      return
    }

    setReorderError(null)
    const targetThread = activeThreads.find((thread) => thread.id === threadId)
    if (targetThread) {
      moveToPositionMutation.mutate({ id: draggedThreadId, position: targetThread.queue_position })
        .then(() => {
          refetch()
          setReorderError(null)
        })
        .catch((error: { response?: { data?: { detail?: string } } }) => {
          setReorderError(error.response?.data?.detail || 'Failed to reorder thread. Please try again.')
        })
    }

    setDraggedThreadId(null)
    setDragOverThreadId(null)
  }

  const handleDragEnd = () => {
    setDraggedThreadId(null)
    setDragOverThreadId(null)
  }

  const handleCreateSubmit = async (event: FormEvent) => {
    event.preventDefault()

    try {
      const isTracked = createForm.trackingMode === 'tracked'
      const hasIssueRange = isTracked && createForm.issues && createForm.issues.trim()

      let issuesRemaining = Number(createForm.issuesRemaining)
      if (hasIssueRange) {
        const { parseIssueRange } = await import('../utils/issueParser')
        issuesRemaining = parseIssueRange(createForm.issues)
      }

      const result = await createMutation.mutate({
        title: createForm.title,
        format: createForm.format,
        issues_remaining: issuesRemaining,
        notes: createForm.notes || null,
      })

      if (hasIssueRange && result?.id) {
        try {
          // Use migrateThread to create issues AND mark 1..lastIssueRead as read in one call
          const lastRead = Number(createForm.lastIssueRead) || 0
          const totalIssues = issuesRemaining
          await issuesApi.migrateThread(result.id, lastRead, totalIssues)
        } catch (issueError: unknown) {
          console.error('Thread created but failed to create issues:', issueError)
          alert(`Thread created successfully, but failed to create individual issues: ${getApiErrorDetail(issueError)}`)
        }
      }

      setCreateForm(DEFAULT_CREATE_STATE)
      setIsCreateOpen(false)
      refetch()
    } catch (error: unknown) {
      console.error('Failed to create thread:', error)
      alert(`Failed to create thread: ${getApiErrorDetail(error)}`)
    }
  }

  const handleEditSubmit = async (event: FormEvent) => {
    event.preventDefault()
    if (!editingThread) return

    try {
      const updateData: { title: string; format: string; notes: string | null; issues_remaining?: number } = {
        title: editForm.title,
        format: editForm.format,
        notes: editForm.notes || null,
      }

      // Include issues_remaining for unmigrated threads
      if (editingThread.total_issues === null) {
        updateData.issues_remaining = Number(editForm.issuesRemaining)
      }

      await updateMutation.mutate({
        id: editingThread.id,
        data: updateData,
      })
      setEditingThread(null)
      setIsEditOpen(false)
      refetch()
    } catch {
      console.error('Failed to update thread')
    }
  }

  const openEditModal = (thread: Thread) => {
    setEditingThread(thread)
    setEditForm({
      title: thread.title,
      format: thread.format,
      issuesRemaining: thread.issues_remaining,
      notes: thread.notes || '',
      issues: '',
      trackingMode: 'simple',
      lastIssueRead: 0,
    })
    setIsEditOpen(true)
  }

  const openReactivateModal = (thread: Thread | null) => {
    setReactivateThreadId(thread?.id ? String(thread.id) : '')
    setIssuesToAdd(1)
    setIsReactivateOpen(true)
  }

  const handleReactivateSubmit = async (event: FormEvent) => {
    event.preventDefault()
    if (!reactivateThreadId) return

    try {
      await reactivateMutation.mutate({
        thread_id: Number(reactivateThreadId),
        issues_to_add: Number(issuesToAdd),
      })
      setIsReactivateOpen(false)
      setReactivateThreadId('')
      setIssuesToAdd(1)
      refetch()
    } catch {
      console.error('Failed to reactivate thread')
    }
  }

  const handleMigrationComplete = useCallback(async (migratedThread: Thread) => {
    try {
      await refetch()
      await refetchSession()
    } catch (error) {
      console.error('Failed to refresh data after migration:', error)
      alert('Failed to refresh data. Please refresh the page.')
    }
    setShowMigrationDialog(false)
    setThreadToMigrate(null)
    setEditingThread(migratedThread)
  }, [refetch, refetchSession])

  const handleMigrationSkip = useCallback(() => {
    setShowMigrationDialog(false)
    setThreadToMigrate(null)
  }, [])

  const handleMigrationClose = useCallback(() => {
    setShowMigrationDialog(false)
    setThreadToMigrate(null)
  }, [])

  const openCreateModal = () => {
    setCreateForm(DEFAULT_CREATE_STATE)
    setIsCreateOpen(true)
  }

  const openRepositionModal = (thread: Thread) => {
    setRepositioningThread(thread)
  }

  function handleThreadClick(thread: Thread) {
    setSelectedThread(thread)
    setIsActionSheetOpen(true)
  }

  async function handleAction(action: string) {
    if (!selectedThread) return

    setIsActionSheetOpen(false)

    const isSnoozed = session?.snoozed_threads?.some((t) => t.id === selectedThread.id) ?? false

    try {
      switch (action) {
        case 'read':
          {
            const isBlocked = blockedThreadIds.includes(selectedThread.id) || selectedThread.is_blocked
            if (isBlocked) {
              const reasons = blockingReasonMap[selectedThread.id] || ['This thread is blocked by a dependency.']
              alert(`Cannot read yet:\n\n${reasons.join('\n')}`)
              break
            }

            const response = await threadsApi.setPending(selectedThread.id)
            navigate('/', { state: { rollResponse: response } })
          }
          break
        case 'move-front':
          await moveToFrontMutation.mutate(selectedThread.id)
          await refetch()
          break
        case 'move-back':
          await moveToBackMutation.mutate(selectedThread.id)
          await refetch()
          break
        case 'snooze':
          if (isSnoozed) {
            await unsnoozeMutation.mutate(selectedThread.id)
          } else {
            await threadsApi.setPending(selectedThread.id)
            await snoozeMutation.mutate()
          }
          await refetchSession()
          await refetch()
          break
        case 'dependencies':
          setDependencyThread(selectedThread)
          setIsDependencyBuilderOpen(true)
          break
        case 'edit':
          openEditModal(selectedThread)
          break
      }
    } catch (error: unknown) {
      console.error('Action failed:', error)
      alert(`Action failed: ${getApiErrorDetail(error)}`)
    }
  }

  const handleRepositionConfirm = async (targetPosition: number) => {
    if (!repositioningThread) return

    if (targetPosition < 1 || targetPosition > activeThreads.length) {
      alert('Invalid position specified. Please choose a valid position.');
      return;
    }

    try {
      await moveToPositionMutation.mutate({ id: repositioningThread.id, position: targetPosition })
      setRepositioningThread(null)
      refetch()
    } catch {
      setRepositioningThread(null)
      alert('Failed to reposition thread. Please try again.')
    }
  }

  if (isPending) {
    return <LoadingSpinner fullScreen />
  }

  return (
    <div className="space-y-10 pb-10">
      <header className="flex justify-between items-start px-2 gap-4">
        <div>
          <h1 className="text-4xl font-black tracking-tighter text-glow mb-1 uppercase">Read Queue</h1>
          <p className="text-[10px] font-bold text-stone-500 uppercase tracking-widest">Your upcoming comics</p>
        </div>
        <button
          type="button"
          onClick={openCreateModal}
          className="h-12 px-5 glass-button text-xs font-black uppercase tracking-widest whitespace-nowrap shadow-xl"
        >
          Add Thread
        </button>
      </header>

      {activeThreads.length === 0 ? (
        <div className="text-center text-stone-500">No active threads in queue</div>
      ) : (
        <>
          {reorderError && (
            <div className="bg-red-500/10 border border-red-500/30 text-red-400 px-4 py-3 rounded-xl text-sm font-medium">
              {reorderError}
            </div>
          )}
          <div
            data-testid="queue-thread-list"
            id="queue-container"
            role="list"
            aria-label="Thread queue"
            className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-2 xl:grid-cols-3 gap-4"
          >
            {activeThreads.map((thread, index) => {
              const isDragOver = dragOverThreadId === thread.id
              const isBlocked = blockedThreadIds.includes(thread.id) || thread.is_blocked
              const blockingReasons = blockingReasonMap[thread.id] || []
              const isMigrated = thread.total_issues !== null

              return (
                <div
                  key={thread.id}
                  data-testid="queue-thread-item"
                  className={`glass-card p-4 space-y-3 group transition-all hover:border-white/20 cursor-pointer ${isDragOver ? 'border-amber-400/60' : ''} ${isBlocked ? 'border-red-400/30 bg-red-500/5' : ''
                    }`}
                  onDragOver={handleDragOver(thread.id)}
                  onDrop={handleDrop(thread.id)}
                  onClick={() => handleThreadClick(thread)}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      handleThreadClick(thread)
                    }
                  }}
                >
                  <div className="flex justify-between items-start gap-3">
                    <div className="flex items-start gap-3 min-w-0 flex-1">
                      <span className="text-2xl font-black text-amber-600/30">
                        #{index + 1}
                      </span>
                      <div className="flex items-center gap-2 min-w-0 flex-1">
                        <Tooltip content="Drag to reorder within the queue.">
                          <button
                            type="button"
                            className="text-stone-500 hover:text-stone-300 transition-colors text-lg"
                            draggable
                            onDragStart={handleDragStart(thread.id)}
                            onDragEnd={handleDragEnd}
                            aria-label="Drag to reorder"
                            onClick={(e) => e.stopPropagation()}
                          >
                            ⠿
                          </button>
                        </Tooltip>
                        <h3 className="text-lg font-bold text-white flex-1 truncate">{thread.title}</h3>
                        {isBlocked && (
                          <Tooltip content={blockingReasons.length > 0 ? blockingReasons.join('\n') : 'Blocked by dependency'}>
                            <span className="text-red-300 text-lg" aria-label="Blocked thread">🔒</span>
                          </Tooltip>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <Tooltip content="Edit thread details.">
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation()
                            openEditModal(thread)
                          }}
                          className="text-stone-500 hover:text-white transition-colors text-sm"
                          aria-label="Edit thread"
                        >
                          ✎
                        </button>
                      </Tooltip>
                      <Tooltip content="Manage dependencies for this thread.">
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation()
                            setDependencyThread(thread)
                            setIsDependencyBuilderOpen(true)
                          }}
                          className="text-stone-500 hover:text-white transition-colors text-sm"
                          aria-label="Manage dependencies"
                        >
                          🔗
                        </button>
                      </Tooltip>
                      <Tooltip content="Delete thread from queue.">
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation()
                            handleDelete(thread.id)
                          }}
                          className="text-stone-500 hover:text-red-400 transition-colors text-xl"
                          aria-label="Delete thread"
                        >
                          &times;
                        </button>
                      </Tooltip>
                    </div>
                  </div>
                  <p className="text-sm text-stone-400">{thread.format}</p>
                  {thread.collection_id && (
                    <div className="mt-1">
                      <CollectionBadge collectionId={thread.collection_id} />
                    </div>
                  )}
                  {thread.notes && <p className="text-xs text-stone-500">{thread.notes}</p>}
                  {thread.issues_remaining !== null && (
                    <p className="text-xs text-stone-500">
                      {isMigrated && thread.next_unread_issue_number
                        ? `Currently on #${thread.next_unread_issue_number} · ${thread.issues_remaining} remaining`
                        : `${thread.issues_remaining} issues remaining`
                      }
                    </p>
                  )}
                  <div className="flex gap-2 pt-2">
                    <Tooltip content="Move this thread to the front of the queue.">
                      <button
                        onClick={(e) => {
                          e.stopPropagation()
                          handleMoveToFront(thread.id)
                        }}
                        className="flex-1 py-2 bg-white/5 border border-white/10 text-stone-400 rounded-xl text-[10px] font-black uppercase tracking-widest hover:bg-white/10 transition-all"
                      >
                        Front
                      </button>
                    </Tooltip>
                    <Tooltip content="Choose a specific position in the queue.">
                      <button
                        onClick={(e) => {
                          e.stopPropagation()
                          openRepositionModal(thread)
                        }}
                        className="flex-1 py-2 bg-white/5 border border-white/10 text-stone-400 rounded-xl text-[10px] font-black uppercase tracking-widest hover:bg-white/10 transition-all"
                      >
                        Reposition
                      </button>
                    </Tooltip>
                    <Tooltip content="Move this thread to the back of the queue.">
                      <button
                        onClick={(e) => {
                          e.stopPropagation()
                          handleMoveToBack(thread.id)
                        }}
                        className="flex-1 py-2 bg-white/5 border border-white/10 text-stone-400 rounded-xl text-[10px] font-black uppercase tracking-widest hover:bg-white/10 transition-all"
                      >
                        Back
                      </button>
                    </Tooltip>
                  </div>
                </div>
              )
            })}
          </div>
        </>
      )}

      <section className="space-y-4">
        <header className="flex items-center justify-between px-2">
          <div>
            <h2 className="text-xl font-black uppercase text-stone-300">Completed Threads</h2>
            <p className="text-[10px] font-bold text-stone-500 uppercase tracking-widest">Reactivate finished series</p>
          </div>
          <button
            type="button"
            onClick={() => openReactivateModal(null)}
            className="h-10 px-4 bg-white/5 border border-white/10 rounded-xl text-[10px] font-black uppercase tracking-widest text-stone-300 hover:bg-white/10"
          >
            Reactivate
          </button>
        </header>
        {completedThreads.length === 0 ? (
          <div className="text-center text-stone-500">No completed threads yet</div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {completedThreads.map((thread) => (
              <div key={thread.id} className="glass-card p-4 space-y-2">
                <div className="flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-sm font-black text-stone-300 truncate">{thread.title}</p>
                    <p className="text-[8px] font-black text-stone-500 uppercase tracking-widest">{thread.format}</p>
                  </div>
                  <button
                    type="button"
                    onClick={() => openReactivateModal(thread)}
                    className="px-3 py-1 bg-white/5 border border-white/10 rounded-lg text-[9px] font-black uppercase tracking-widest text-stone-300 hover:bg-white/10"
                  >
                    Reactivate
                  </button>
                </div>
                {thread.notes && <p className="text-xs text-stone-500">{thread.notes}</p>}
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Create Thread Modal */}
      <Modal isOpen={isCreateOpen} title="Create Thread" onClose={() => setIsCreateOpen(false)}>
        <form className="space-y-4" onSubmit={handleCreateSubmit}>
          <div className="space-y-2">
            <label className="text-[10px] font-bold uppercase tracking-widest text-stone-500">Title</label>
            <input
              value={createForm.title}
              onChange={(event) => setCreateForm({ ...createForm, title: event.target.value })}
              className="w-full bg-white/5 border border-white/10 rounded-xl px-3 py-2 text-sm text-stone-300"
              required
            />
          </div>
          <div className="space-y-2">
            <label className="text-[10px] font-bold uppercase tracking-widest text-stone-500">Format</label>
            <FormatSelect
              value={createForm.format}
              onChange={(value) => setCreateForm({ ...createForm, format: value })}
              required
            />
          </div>

          {/* Tracking mode toggle */}
          <div className="space-y-2">
            <label className="text-[10px] font-bold uppercase tracking-widest text-stone-500">Issue Tracking</label>
            <div className="grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => setCreateForm({ ...createForm, trackingMode: 'simple' })}
                className={`py-2 rounded-xl border text-xs font-black uppercase tracking-widest ${
                  createForm.trackingMode === 'simple'
                    ? 'bg-amber-600/20 border-amber-500/40 text-amber-300'
                    : 'bg-white/5 border-white/10 text-stone-400'
                }`}
              >
                Simple counter
              </button>
              <button
                type="button"
                onClick={() => setCreateForm({ ...createForm, trackingMode: 'tracked' })}
                className={`py-2 rounded-xl border text-xs font-black uppercase tracking-widest ${
                  createForm.trackingMode === 'tracked'
                    ? 'bg-amber-600/20 border-amber-500/40 text-amber-300'
                    : 'bg-white/5 border-white/10 text-stone-400'
                }`}
              >
                Track individual issues
              </button>
            </div>
          </div>

          {createForm.trackingMode === 'simple' ? (
            <div className="space-y-2">
              <label className="text-[10px] font-bold uppercase tracking-widest text-stone-500">Issues Remaining</label>
              <input
                type="number"
                min="0"
                value={createForm.issuesRemaining}
                onChange={(event: ChangeEvent<HTMLInputElement>) =>
                  setCreateForm({
                    ...createForm,
                    issuesRemaining: Number.parseInt(event.target.value, 10) || 0,
                  })
                }
                className="w-full bg-white/5 border border-white/10 rounded-xl px-3 py-2 text-sm text-stone-300"
                required
              />
            </div>
          ) : (
            <>
              <div className="space-y-2">
                <label className="text-[10px] font-bold uppercase tracking-widest text-stone-500">Issues</label>
                <input
                  type="text"
                  value={createForm.issues}
                  onChange={(event) => setCreateForm({ ...createForm, issues: event.target.value })}
                  className="w-full bg-white/5 border border-white/10 rounded-xl px-3 py-2 text-sm text-stone-300"
                  placeholder="0-25 or 0, ½, Annual 1, 5-7"
                  required
                />
                {issuePreview !== null && (
                  <p className="text-xs text-stone-400">
                    Will create {issuePreview} issue{issuePreview !== 1 ? 's' : ''}
                  </p>
                )}
                {issueParseError && (
                  <p className="text-xs text-red-400">{issueParseError}</p>
                )}
              </div>
              <div className="space-y-2">
                <label className="text-[10px] font-bold uppercase tracking-widest text-stone-500">Last issue read (optional)</label>
                <input
                  type="number"
                  min="0"
                  value={createForm.lastIssueRead}
                  onChange={(event: ChangeEvent<HTMLInputElement>) =>
                    setCreateForm({
                      ...createForm,
                      lastIssueRead: Number.parseInt(event.target.value, 10) || 0,
                    })
                  }
                  className="w-full bg-white/5 border border-white/10 rounded-xl px-3 py-2 text-sm text-stone-300"
                />
                {createForm.lastIssueRead > 0 && issuePreview !== null && (
                  <p className="text-xs text-stone-400">
                    Issues #1–{createForm.lastIssueRead} will be marked as read
                  </p>
                )}
              </div>
            </>
          )}

          <div className="space-y-2">
            <label className="text-[10px] font-bold uppercase tracking-widest text-stone-500">Notes</label>
            <textarea
              value={createForm.notes}
              onChange={(event) => setCreateForm({ ...createForm, notes: event.target.value })}
              className="w-full bg-white/5 border border-white/10 rounded-xl px-3 py-2 text-sm text-stone-300 min-h-[80px]"
            ></textarea>
          </div>
          <button
            type="submit"
            disabled={createMutation.isPending}
            className="w-full py-3 glass-button text-xs font-black uppercase tracking-widest disabled:opacity-60"
          >
            {createMutation.isPending ? 'Creating...' : 'Create Thread'}
          </button>
        </form>
      </Modal>

      {/* Edit Thread Modal */}
      <Modal isOpen={isEditOpen} title="Edit Thread" onClose={() => { setIsEditOpen(false); refetch() }} overlayClassName="edit-modal__overlay">
        <div className="space-y-4">
          <form id="edit-thread-form" className="space-y-4" onSubmit={handleEditSubmit}>
            <div className="space-y-2">
              <label className="text-[10px] font-bold uppercase tracking-widest text-stone-500">Title</label>
              <input
                value={editForm.title}
                onChange={(event) => setEditForm({ ...editForm, title: event.target.value })}
                className="w-full bg-white/5 border border-white/10 rounded-xl px-3 py-2 text-sm text-stone-300"
                required
              />
            </div>

            <div className="space-y-2">
              <label className="text-[10px] font-bold uppercase tracking-widest text-stone-500">Format</label>
              <FormatSelect
                value={editForm.format}
                onChange={(value) => setEditForm({ ...editForm, format: value })}
                required
              />
            </div>

            {/* Issues remaining for unmigrated threads */}
            {editingThread?.total_issues === null && (
              <div className="space-y-2">
                <label className="text-[10px] font-bold uppercase tracking-widest text-stone-500">Issues Remaining</label>
                <input
                  type="number"
                  min="0"
                  value={editForm.issuesRemaining}
                  onChange={(event: ChangeEvent<HTMLInputElement>) =>
                    setEditForm({
                      ...editForm,
                      issuesRemaining: Number.parseInt(event.target.value, 10) || 0,
                    })
                  }
                  className="w-full bg-white/5 border border-white/10 rounded-xl px-3 py-2 text-sm text-stone-300"
                />
              </div>
            )}

            <div className="space-y-2">
              <label className="text-[10px] font-bold uppercase tracking-widest text-stone-500">Notes</label>
              <textarea
                value={editForm.notes}
                onChange={(event) => setEditForm({ ...editForm, notes: event.target.value })}
                className="w-full bg-white/5 border border-white/10 rounded-xl px-3 py-2 text-sm text-stone-300 min-h-[80px]"
              ></textarea>
            </div>

            {editingThread?.total_issues === null && (
              <div className="space-y-2 pt-2 border-t border-white/10">
                <button
                  type="button"
                  onClick={() => {
                    setThreadToMigrate(editingThread)
                    setShowMigrationDialog(true)
                  }}
                  className="edit-modal__migration-button w-full py-3 px-4 bg-amber-500/10 border border-amber-500/30 rounded-xl text-left text-xs font-black text-amber-300 hover:bg-amber-500/20 transition-all flex items-center gap-3"
                >
                  <span className="text-lg">📊</span>
                  <div className="flex-1">
                    <div className="font-bold">Migrate to Issue Tracking</div>
                    <div className="font-normal text-stone-400 mt-0.5">Track individual issues instead of remaining count</div>
                  </div>
                </button>
              </div>
            )}
          </form>

          {/* Issue list for migrated threads lives outside the edit form so Enter only adds issues. */}
          {editingThread && editingThread.total_issues !== null && (
            <IssueToggleList threadId={editingThread.id} />
          )}

          <button
            type="submit"
            form="edit-thread-form"
            disabled={updateMutation.isPending}
            className="w-full py-3 glass-button text-xs font-black uppercase tracking-widest disabled:opacity-60"
          >
            {updateMutation.isPending ? 'Saving...' : 'Save Changes'}
          </button>
        </div>
      </Modal>

      <Modal isOpen={isReactivateOpen} title="Reactivate Thread" onClose={() => setIsReactivateOpen(false)}>
        <form className="space-y-4" onSubmit={handleReactivateSubmit}>
          <div className="space-y-2">
            <label className="text-[10px] font-bold uppercase tracking-widest text-stone-500">Completed Thread</label>
            <select
              value={reactivateThreadId}
              onChange={(event) => setReactivateThreadId(event.target.value)}
              className="w-full bg-white/5 border border-white/10 rounded-xl px-3 py-2 text-sm text-stone-300"
              required
            >
              <option value="">Select a thread...</option>
              {completedThreads.map((thread) => (
                  <option key={thread.id} value={String(thread.id)}>
                  {thread.title} ({thread.format})
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-2">
            <label className="text-[10px] font-bold uppercase tracking-widest text-stone-500">Issues to Add</label>
            <input
              type="number"
              min="1"
              value={issuesToAdd}
              onChange={(event) => setIssuesToAdd(Number.parseInt(event.target.value, 10) || 1)}
              className="w-full bg-white/5 border border-white/10 rounded-xl px-3 py-2 text-sm text-stone-300"
              required
            />
          </div>
          <button
            type="submit"
            disabled={reactivateMutation.isPending}
            className="w-full py-3 glass-button text-xs font-black uppercase tracking-widest disabled:opacity-60"
          >
            {reactivateMutation.isPending ? 'Reactivating...' : 'Reactivate Thread'}
          </button>
        </form>
      </Modal>

      <Modal
        isOpen={repositioningThread !== null}
        title={`Reposition: ${repositioningThread?.title ?? ''}`}
        onClose={() => setRepositioningThread(null)}
        data-testid="position-slider-modal"
      >
        {repositioningThread && (
          <PositionSlider
            threads={activeThreads}
            currentThread={repositioningThread}
            onPositionSelect={handleRepositionConfirm}
            onCancel={() => setRepositioningThread(null)}
          />
        )}
      </Modal>

      <Modal isOpen={isActionSheetOpen} title={selectedThread?.title} onClose={() => setIsActionSheetOpen(false)}>
        <div className="space-y-2">
          <button
            type="button"
            onClick={() => handleAction('read')}
            className="w-full py-3 px-4 bg-white/5 border border-white/10 rounded-xl text-left text-sm font-black text-stone-300 hover:bg-white/10 transition-all flex items-center gap-3"
          >
            <span className="text-lg">📖</span>
            <span>Read Now</span>
          </button>
          <button
            type="button"
            onClick={() => handleAction('move-front')}
            className="w-full py-3 px-4 bg-white/5 border border-white/10 rounded-xl text-left text-sm font-black text-stone-300 hover:bg-white/10 transition-all flex items-center gap-3"
          >
            <span className="text-lg">⬆️</span>
            <span>Move to Front</span>
          </button>
          <button
            type="button"
            onClick={() => handleAction('move-back')}
            className="w-full py-3 px-4 bg-white/5 border border-white/10 rounded-xl text-left text-sm font-black text-stone-300 hover:bg-white/10 transition-all flex items-center gap-3"
          >
            <span className="text-lg">⬇️</span>
            <span>Move to Back</span>
          </button>
          <button
            type="button"
            onClick={() => handleAction('snooze')}
            className="w-full py-3 px-4 bg-white/5 border border-white/10 rounded-xl text-left text-sm font-black text-stone-300 hover:bg-white/10 transition-all flex items-center gap-3"
          >
            <span className="text-lg">{session?.snoozed_threads?.some((t) => t.id === selectedThread?.id) ? '🔔' : '😴'}</span>
            <span>{session?.snoozed_threads?.some((t) => t.id === selectedThread?.id) ? 'Unsnooze' : 'Snooze'}</span>
          </button>
          <button
            type="button"
            onClick={() => handleAction('dependencies')}
            className="w-full py-3 px-4 bg-white/5 border border-white/10 rounded-xl text-left text-sm font-black text-stone-300 hover:bg-white/10 transition-all flex items-center gap-3"
          >
            <span className="text-lg">🔗</span>
            <span>Dependencies</span>
          </button>
          <button
            type="button"
            onClick={() => handleAction('edit')}
            className="w-full py-3 px-4 bg-white/5 border border-white/10 rounded-xl text-left text-sm font-black text-stone-300 hover:bg-white/10 transition-all flex items-center gap-3"
          >
            <span className="text-lg">✏️</span>
            <span>Edit Thread</span>
          </button>
        </div>
      </Modal>

      <DependencyBuilder
        thread={dependencyThread}
        isOpen={isDependencyBuilderOpen}
        onClose={() => {
          setIsDependencyBuilderOpen(false)
          setDependencyThread(null)
        }}
        onChanged={async () => {
          await refetch()
          await refreshBlockedState()
        }}
      />

      {showMigrationDialog && threadToMigrate && (
        <MigrationDialog
          thread={threadToMigrate}
          onComplete={handleMigrationComplete}
          onSkip={handleMigrationSkip}
          onClose={handleMigrationClose}
        />
      )}
    </div>
  )
}
