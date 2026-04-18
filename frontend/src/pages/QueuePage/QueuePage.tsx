import { useState, useEffect, useCallback } from 'react'
import type { ChangeEvent, DragEvent, FormEvent } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import Modal from '../../components/Modal'
import PositionMenu from '../../components/PositionMenu'
import PositionSlider from '../../components/PositionSlider'
import Tooltip from '../../components/Tooltip'
import LoadingSpinner from '../../components/LoadingSpinner'
import DependencyBuilder from '../../components/DependencyBuilder'
import MigrationDialog from '../../components/MigrationDialog'
import CollectionDialog from '../../components/CollectionDialog'
import CollectionToolbar from '../../components/CollectionToolbar'
import { useMoveToBack, useMoveToFront, useMoveToPosition } from '../../hooks/useQueue'
import { useCreateThread, useDeleteThread, useReactivateThread, useThreads, useUpdateThread } from '../../hooks/useThread'
import { useSession } from '../../hooks/useSession'
import { useSnooze, useUnsnooze } from '../../hooks/useSnooze'
import { dependenciesApi, threadsApi } from '../../services/api'
import { issuesApi } from '../../services/api-issues'
import { useBugReportRestore } from '../../contexts/BugReportRestoreContext'
import { useCollections } from '../../contexts/CollectionContext'
import { PositionMenuProvider } from '../../contexts/PositionMenuContext'
import type { Thread } from '../../types'
import { getApiErrorDetail } from '../../utils/apiError'
import { CollectionBadge } from './CollectionBadge'
import { FormatSelect } from './FormatSelect'
import { IssueToggleList } from './IssueToggleList'
import { DEFAULT_CREATE_STATE, type QueueFormState } from './types'

export default function QueuePage() {
  const navigate = useNavigate()
  const location = useLocation()
  const { activeCollectionId } = useCollections()
  const { setRestoreAction, clearRestoreAction } = useBugReportRestore()
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
  const [isCollectionDialogOpen, setIsCollectionDialogOpen] = useState(false)
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

  const openActionSheet = (thread: Thread) => {
    setSelectedThread(thread)
    setIsActionSheetOpen(true)
  }
  const [showMigrationDialog, setShowMigrationDialog] = useState(false)
  const [threadToMigrate, setThreadToMigrate] = useState<Thread | null>(null)
  const [blockedThreadIds, setBlockedThreadIds] = useState<number[]>([])
  const [blockingReasonMap, setBlockingReasonMap] = useState<Record<number, string[]>>({})
  const [dependencyThread, setDependencyThread] = useState<Thread | null>(null)
  const [isDependencyBuilderOpen, setIsDependencyBuilderOpen] = useState(false)
  const [issuePreview, setIssuePreview] = useState<number | null>(null)
  const [issueParseError, setIssueParseError] = useState<string | null>(null)

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
    let cancelled = false
    const calculatePreview = async () => {
      const issueInput = createForm.issues
      if (issueInput) {
        try {
          const { parseIssueRange } = await import('../../utils/issueParser')
          const total = parseIssueRange(issueInput)
          if (cancelled) return
          setIssuePreview(total)
          setIssueParseError(null)
        } catch (err) {
          if (cancelled) return
          setIssuePreview(null)
          setIssueParseError(err instanceof Error ? err.message : 'Invalid issue range')
        }
      } else {
        if (cancelled) return
        setIssuePreview(null)
        setIssueParseError(null)
      }
    }
    calculatePreview()

    return () => {
      cancelled = true
    }
  }, [createForm.issues])

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
        .catch((error: unknown) => {
          setReorderError(getApiErrorDetail(error) || 'Failed to reorder thread. Please try again.')
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
      const hasIssueRange = createForm.issues && createForm.issues.trim()

      let issuesRemaining = Number(createForm.issuesRemaining)
      if (hasIssueRange) {
        const { parseIssueRange } = await import('../../utils/issueParser')
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
          // Check if the range is a simple contiguous integer sequence starting from 1 (e.g., "1-25")
          const rangeMatch = createForm.issues.trim().match(/^(\d+)-(\d+)$/)
          const isSimpleRange = !!rangeMatch && Number(rangeMatch[1]) === 1
          
          if (isSimpleRange) {
            // Use migrateThread for simple ranges starting from 1 (creates sequential issues 1..N)
            const requestedLastRead = Number(createForm.lastIssueRead) || 0
            const lastRead = Math.max(0, Math.min(requestedLastRead, issuesRemaining))
            await issuesApi.migrateThread(result.id, lastRead, issuesRemaining)
          } else {
            // Use issuesApi.create for complex ranges (preserves non-contiguous/non-integer identifiers)
            const issueListResponse = await issuesApi.create(result.id, createForm.issues.trim())
            
            // Mark issues as read if lastIssueRead is specified
            const requestedLastRead = Number(createForm.lastIssueRead) || 0
            const lastRead = Math.max(0, Math.min(requestedLastRead, issueListResponse.issues.length))
            if (lastRead > 0 && issueListResponse.issues.length > 0) {
              // Mark the first N issues as read
              const issuesToMark = issueListResponse.issues.slice(0, lastRead)
              await Promise.all(issuesToMark.map(issue => issuesApi.markRead(issue.id)))
            }
          }
        } catch (issueError: unknown) {
          console.error('Thread created but failed to create issues:', issueError)
          alert(`Thread created successfully, but failed to create individual issues: ${getApiErrorDetail(issueError)}`)
        }
      }

      setCreateForm(DEFAULT_CREATE_STATE)
      closeCreateModal()
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
      closeEditModal()
    } catch {
      console.error('Failed to update thread')
    }
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

  const clearQueueModalState = useCallback(() => {
    navigate(location.pathname, { replace: true, state: {} })
  }, [location.pathname, navigate])

  const openCreateModal = useCallback(() => {
    setCreateForm(DEFAULT_CREATE_STATE)
    setIsCreateOpen(true)
    setRestoreAction(() => {
      setCreateForm(DEFAULT_CREATE_STATE)
      setIsCreateOpen(true)
    })
    navigate(location.pathname, {
      replace: true,
      state: {
        ...(location.state ?? {}),
        openCreate: true,
      },
    })
  }, [location.pathname, location.state, navigate, setRestoreAction])

  const closeCreateModal = useCallback(() => {
    setIsCreateOpen(false)
    clearRestoreAction()
    clearQueueModalState()
  }, [clearQueueModalState, clearRestoreAction])

  const openEditModal = useCallback((thread: Thread) => {
    setEditingThread(thread)
    setEditForm({
      title: thread.title,
      format: thread.format,
      issuesRemaining: thread.issues_remaining,
      notes: thread.notes || '',
      issues: '',
      lastIssueRead: 0,
    })
    setIsEditOpen(true)
    setRestoreAction(() => {
      setEditingThread(thread)
      setEditForm({
        title: thread.title,
        format: thread.format,
        issuesRemaining: thread.issues_remaining,
        notes: thread.notes || '',
        issues: '',
        lastIssueRead: 0,
      })
      setIsEditOpen(true)
    })
    navigate(location.pathname, {
      replace: true,
      state: {
        ...(location.state ?? {}),
        editThreadId: thread.id,
      },
    })
  }, [location.pathname, location.state, navigate, setRestoreAction])

  const closeEditModal = useCallback(() => {
    setEditingThread(null)
    setIsEditOpen(false)
    clearRestoreAction()
    clearQueueModalState()
    refetch()
  }, [clearQueueModalState, clearRestoreAction, refetch])

  useEffect(() => {
    if (location.state?.editThreadId && threads) {
      const thread = threads.find((t) => t.id === location.state.editThreadId)
      if (thread && (!isEditOpen || editingThread?.id !== thread.id)) {
        openEditModal(thread)
      }
    }
    if (location.state?.openCreate && !isCreateOpen) {
      openCreateModal()
    }
  }, [editingThread?.id, isCreateOpen, isEditOpen, location.pathname, location.state, openCreateModal, openEditModal, threads])

  const openRepositionModal = (thread: Thread) => {
    setRepositioningThread(thread)
  }

  function handleThreadClick(thread: Thread) {
    navigate(`/thread/${thread.id}`)
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
          navigate(`/thread/${selectedThread.id}`)
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
    <PositionMenuProvider>
      <div className="space-y-10 pb-10">
      <header className="space-y-4 px-2">
        <div className="flex justify-between items-start gap-4">
          <div>
            <h1 className="text-4xl font-black tracking-tighter text-glow mb-1 uppercase">Read Queue</h1>
            <p className="text-[10px] font-bold text-stone-500 uppercase tracking-widest">Your upcoming comics</p>
          </div>
          <button
            type="button"
            onClick={openCreateModal}
            className="hidden md:flex h-12 px-5 glass-button text-xs font-black uppercase tracking-widest whitespace-nowrap shadow-xl"
          >
            Add Thread
          </button>
        </div>
        <CollectionToolbar onNewCollection={() => setIsCollectionDialogOpen(true)} />
      </header>

      {/* Mobile FAB for Add Thread */}
      <button
        type="button"
        onClick={openCreateModal}
        className="md:hidden fixed bottom-24 right-4 h-14 w-14 rounded-full bg-amber-600 text-white font-black text-3xl shadow-[0_4px_20px_rgba(212,137,14,0.4)] z-50 flex items-center justify-center hover:bg-amber-500 transition-colors"
        aria-label="Add Thread"
      >
        +
      </button>

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
                         <h3 className="text-lg font-bold text-white flex-1 line-clamp-2">{thread.title}</h3>
                        {isBlocked && (
                          <Tooltip content={blockingReasons.length > 0 ? blockingReasons.join('\n') : 'Blocked by dependency'}>
                            <span className="text-red-300 text-lg" aria-label="Blocked thread">🔒</span>
                          </Tooltip>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-1">
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
        <PositionMenu
          thread={thread}
          onMoveToFront={handleMoveToFront}
          onReposition={openRepositionModal}
          onMoveToBack={handleMoveToBack}
        />
      </div>
      {/* Mobile 3-dot menu indicator */}
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation()
          openActionSheet(thread)
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            e.stopPropagation()
            openActionSheet(thread)
          }
        }}
        className="md:hidden text-stone-500 flex items-center justify-center w-8 h-8 text-xl"
        aria-label="Open actions"
      >
        ⋮
      </button>
                  </div>
                  <div className="pl-[2.75rem]">
                    <p className="text-xs text-stone-500 uppercase tracking-widest font-bold">{thread.format}</p>
                    {thread.collection_id && (
                      <div className="mt-1.5 flex">
                        <CollectionBadge collectionId={thread.collection_id} />
                      </div>
                    )}
                    {thread.notes && <p className="text-xs text-stone-400 mt-2">{thread.notes}</p>}
                    {thread.issues_remaining !== null && (
                      <p className="text-sm text-stone-300 mt-2 font-medium">
                         {isMigrated && thread.next_unread_issue_number
                           ? `Up next: #${thread.next_unread_issue_number} · ${thread.issues_remaining} remaining`
                           : `${thread.issues_remaining} issues remaining`
                         }
                      </p>
                    )}
                    {isBlocked && blockingReasons.length > 0 && (
                      <button
                        type="button"
                        className="mt-2 w-full text-left text-xs text-red-300/80 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2 hover:bg-red-500/15 transition-colors"
                        onClick={(e) => {
                          e.stopPropagation()
                          setDependencyThread(thread)
                          setIsDependencyBuilderOpen(true)
                        }}
                        aria-label={`View dependencies for ${thread.title}`}
                      >
                        <span className="font-bold">🔒 {blockingReasons[0]}</span>
                        {blockingReasons.length > 1 && (
                          <span className="text-red-400/60 ml-1">+{blockingReasons.length - 1} more</span>
                        )}
                      </button>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </>
      )}

      {completedThreads.length > 0 && (
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
      </section>
      )}

  {/* Create Thread Modal */}
  <Modal isOpen={isCreateOpen} title="Create Thread" onClose={closeCreateModal}>
  <form className="space-y-4" onSubmit={handleCreateSubmit}>
  <div className="space-y-2">
  <label htmlFor="create-thread-title" className="text-[10px] font-bold uppercase tracking-widest text-stone-500">Title</label>
  <input
  id="create-thread-title"
  value={createForm.title}
  onChange={(event) => setCreateForm({ ...createForm, title: event.target.value })}
  className="w-full bg-white/5 border border-white/10 rounded-xl px-3 py-2 text-sm text-stone-300"
  required
  />
  </div>
  <div className="space-y-2">
  <label htmlFor="create-thread-format" className="text-[10px] font-bold uppercase tracking-widest text-stone-500">Format</label>
  <FormatSelect
  id="create-thread-format"
  value={createForm.format}
  onChange={(value) => setCreateForm({ ...createForm, format: value })}
  required
  />
  </div>

  <div className="space-y-2">
  <label htmlFor="create-thread-issues" className="text-[10px] font-bold uppercase tracking-widest text-stone-500">Issues</label>
  <input
  id="create-thread-issues"
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
  <label htmlFor="create-thread-last-read" className="text-[10px] font-bold uppercase tracking-widest text-stone-500">Last issue read (optional)</label>
  <input
  id="create-thread-last-read"
  type="number"
  min="0"
  max={issuePreview ?? undefined}
  value={createForm.lastIssueRead}
  onChange={(event: ChangeEvent<HTMLInputElement>) => {
  const value = Number.parseInt(event.target.value, 10) || 0
  const clampedValue = issuePreview !== null ? Math.min(value, issuePreview) : value
  setCreateForm({
  ...createForm,
  lastIssueRead: clampedValue,
  })
  }}
  className="w-full bg-white/5 border border-white/10 rounded-xl px-3 py-2 text-sm text-stone-300"
  />
            {createForm.lastIssueRead > 0 && issuePreview !== null && (
              <p className="text-xs text-stone-400">
                First {Math.min(createForm.lastIssueRead, issuePreview)} issues (in creation order) of {issuePreview} will be marked as read
              </p>
            )}
            {createForm.lastIssueRead > 0 && issuePreview !== null && createForm.lastIssueRead > issuePreview && (
              <p className="text-xs text-amber-400">
                Last issue read cannot exceed total issues ({issuePreview})
              </p>
            )}
          </div>

  <div className="space-y-2">
  <label htmlFor="create-thread-notes" className="text-[10px] font-bold uppercase tracking-widest text-stone-500">Notes</label>
  <textarea
  id="create-thread-notes"
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
  <Modal isOpen={isEditOpen} title="Edit Thread" onClose={closeEditModal} overlayClassName="edit-modal__overlay">
  <div className="space-y-4">
  <form id="edit-thread-form" className="space-y-4" onSubmit={handleEditSubmit}>
  <div className="space-y-2">
  <label htmlFor="edit-thread-title" className="text-[10px] font-bold uppercase tracking-widest text-stone-500">Title</label>
  <input
  id="edit-thread-title"
  value={editForm.title}
  onChange={(event) => setEditForm({ ...editForm, title: event.target.value })}
  className="w-full bg-white/5 border border-white/10 rounded-xl px-3 py-2 text-sm text-stone-300"
  required
  />
  </div>

  <div className="space-y-2">
  <label htmlFor="edit-thread-format" className="text-[10px] font-bold uppercase tracking-widest text-stone-500">Format</label>
  <FormatSelect
  id="edit-thread-format"
  value={editForm.format}
  onChange={(value) => setEditForm({ ...editForm, format: value })}
  required
  />
  </div>

  {/* Issues remaining for unmigrated threads */}
  {editingThread?.total_issues === null && (
  <div className="space-y-2">
  <label htmlFor="edit-thread-issues-remaining" className="text-[10px] font-bold uppercase tracking-widest text-stone-500">Issues Remaining</label>
  <input
  id="edit-thread-issues-remaining"
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
  <label htmlFor="edit-thread-notes" className="text-[10px] font-bold uppercase tracking-widest text-stone-500">Notes</label>
  <textarea
  id="edit-thread-notes"
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

      <Modal isOpen={isActionSheetOpen} title={selectedThread?.title ?? ''} onClose={() => setIsActionSheetOpen(false)}>
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

      {isCollectionDialogOpen && <CollectionDialog onClose={() => setIsCollectionDialogOpen(false)} />}

      {showMigrationDialog && threadToMigrate && (
        <MigrationDialog
          thread={threadToMigrate}
          onComplete={handleMigrationComplete}
          onSkip={handleMigrationSkip}
          onClose={handleMigrationClose}
        />
       )}
     </div>
     </PositionMenuProvider>
   )
 }
