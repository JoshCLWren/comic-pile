import { useCallback, useEffect, useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import type { Thread } from '../../types'
import { issuesApi } from '../../services/api-issues'
import { useBugReportRestore } from '../../contexts/useBugReportRestore'
import { getApiErrorDetail } from '../../utils/apiError'
import { DEFAULT_CREATE_STATE, type QueueFormState } from './types'

type ModalKey =
  | 'create'
  | 'edit'
  | 'reactivate'
  | 'dependency'
  | 'reposition'
  | 'migration'

interface QueueModalsParams {
  threads: Thread[] | null | undefined
  onCreated: () => Promise<unknown> | unknown
  onUpdated: () => Promise<unknown> | unknown
  onReactivated: () => Promise<unknown> | unknown
  refetchSession: () => Promise<unknown> | unknown
  submitCreate: (input: {
    title: string
    format: string
    issues_remaining: number
    notes: string | null
  }) => Promise<{ id?: number } | unknown>
  submitEdit: (input: {
    id: number
    data: { title: string; format: string; notes: string | null; issues_remaining?: number }
  }) => Promise<unknown>
  submitReactivate: (input: {
    thread_id: number
    issues_to_add: number
  }) => Promise<unknown>
  isPendingCreate: boolean
  isPendingEdit: boolean
}

interface UseQueueModalsResult {
  openModal: ModalKey | null
  isAnyModalOpen: boolean
  createForm: QueueFormState
  editForm: QueueFormState
  issuePreview: number | null
  issueParseError: string | null
  editingThread: Thread | null
  repositioningThread: Thread | null
  dependencyThread: Thread | null
  threadToMigrate: Thread | null
  showMigrationDialog: boolean
  reactivateThreadId: string
  issuesToAdd: number
  setCreateForm: (next: QueueFormState) => void
  setEditForm: (next: QueueFormState) => void
  setReactivateThreadId: (next: string) => void
  setIssuesToAdd: (next: number) => void
  showCreateModal: () => void
  closeCreateModal: () => void
  showEditModal: (thread: Thread) => void
  closeEditModal: () => void
  openReactivateModal: (thread: Thread | null) => void
  closeReactivateModal: () => void
  openRepositionModal: (thread: Thread) => void
  closeRepositionModal: () => void
  openDependenciesModal: (thread: Thread) => void
  closeDependenciesModal: () => void
  openMigrationDialog: (thread: Thread) => void
  closeMigrationDialog: () => void
  handleCreateSubmit: (event: FormEvent) => Promise<void>
  handleEditSubmit: (event: FormEvent) => Promise<void>
  handleReactivateSubmit: (event: FormEvent) => Promise<void>
  handleMigrationComplete: (migratedThread: Thread) => Promise<void>
  handleMigrationSkip: () => void
  isPendingCreate: boolean
  isPendingEdit: boolean
}

/**
 * Centralized modal lifecycle, restore-action registration, and form state for
 * every modal the Queue page coordinates. The hook returns plain handlers and
 * presentational state so the page can compose the modal modules without
 * re-implementing the navigation, bug-report-restore, or location-state wiring.
 */
export function useQueueModals(params: QueueModalsParams): UseQueueModalsResult {
  const {
    threads,
    onCreated,
    onUpdated,
    onReactivated,
    refetchSession,
    submitCreate,
    submitEdit,
    submitReactivate,
    isPendingCreate,
    isPendingEdit,
  } = params
  const navigate = useNavigate()
  const location = useLocation()
  const { setRestoreAction, clearRestoreAction } = useBugReportRestore()

  const [openModal, setOpenModal] = useState<ModalKey | null>(null)
  const [createForm, setCreateForm] = useState<QueueFormState>(DEFAULT_CREATE_STATE)
  const [editForm, setEditForm] = useState<QueueFormState>(DEFAULT_CREATE_STATE)
  const [editingThread, setEditingThread] = useState<Thread | null>(null)
  const [reactivateThreadId, setReactivateThreadId] = useState('')
  const [issuesToAdd, setIssuesToAdd] = useState(1)
  const [repositioningThread, setRepositioningThread] = useState<Thread | null>(null)
  const [dependencyThread, setDependencyThread] = useState<Thread | null>(null)
  const [threadToMigrate, setThreadToMigrate] = useState<Thread | null>(null)
  const [showMigrationDialog, setShowMigrationDialog] = useState(false)
  const [issuePreview, setIssuePreview] = useState<number | null>(null)
  const [issueParseError, setIssueParseError] = useState<string | null>(null)

  const clearQueueModalState = useCallback(() => {
    navigate(location.pathname, { replace: true, state: {} })
  }, [location.pathname, navigate])

  const showCreateModal = useCallback(() => {
    setCreateForm(DEFAULT_CREATE_STATE)
    setOpenModal('create')
    setRestoreAction(() => {
      setCreateForm(DEFAULT_CREATE_STATE)
      setOpenModal('create')
    })
  }, [setRestoreAction])

  const closeCreateModal = useCallback(() => {
    setOpenModal(null)
    clearRestoreAction()
    clearQueueModalState()
  }, [clearQueueModalState, clearRestoreAction])

  const showEditModal = useCallback(
    (thread: Thread) => {
      setEditingThread(thread)
      setEditForm({
        title: thread.title,
        format: thread.format,
        issuesRemaining: thread.issues_remaining,
        notes: thread.notes || '',
        issues: '',
        lastIssueRead: 0,
      })
      setOpenModal('edit')
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
        setOpenModal('edit')
      })
    },
    [setRestoreAction],
  )

  const closeEditModal = useCallback(() => {
    setEditingThread(null)
    setOpenModal(null)
    clearRestoreAction()
    clearQueueModalState()
  }, [clearQueueModalState, clearRestoreAction])

  const openReactivateModal = useCallback((thread: Thread | null) => {
    setReactivateThreadId(thread?.id ? String(thread.id) : '')
    setIssuesToAdd(1)
    setOpenModal('reactivate')
  }, [])

  const closeReactivateModal = useCallback(() => {
    setOpenModal(null)
  }, [])

  const openRepositionModal = useCallback((thread: Thread) => {
    setRepositioningThread(thread)
    setOpenModal('reposition')
  }, [])

  const closeRepositionModal = useCallback(() => {
    setRepositioningThread(null)
    setOpenModal(null)
  }, [])

  const openDependenciesModal = useCallback((thread: Thread) => {
    setDependencyThread(thread)
    setOpenModal('dependency')
  }, [])

  const closeDependenciesModal = useCallback(() => {
    setDependencyThread(null)
    setOpenModal(null)
  }, [])

  const openMigrationDialog = useCallback((thread: Thread) => {
    setThreadToMigrate(thread)
    setShowMigrationDialog(true)
  }, [])

  const closeMigrationDialog = useCallback(() => {
    setShowMigrationDialog(false)
    setThreadToMigrate(null)
  }, [])

  useEffect(() => {
    if (location.state?.editThreadId && threads) {
      const thread = threads.find((t) => t.id === location.state.editThreadId)
      if (thread && (openModal !== 'edit' || editingThread?.id !== thread.id)) {
        showEditModal(thread)
      }
      clearQueueModalState()
      return
    }
    if (location.state?.openCreate && openModal !== 'create') {
      showCreateModal()
      clearQueueModalState()
    }
  }, [
    clearQueueModalState,
    editingThread?.id,
    location.state,
    openModal,
    showCreateModal,
    showEditModal,
    threads,
  ])

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

  const handleCreateSubmit = useCallback(
    async (event: FormEvent) => {
      event.preventDefault()
      const { parseIssueRange } = await import('../../utils/issueParser')
      const hasIssueRange = Boolean(createForm.issues && createForm.issues.trim())
      let issuesRemaining = Number(createForm.issuesRemaining)
      if (hasIssueRange) {
        issuesRemaining = parseIssueRange(createForm.issues)
      }
      try {
        const result = (await submitCreate({
          title: createForm.title,
          format: createForm.format,
          issues_remaining: issuesRemaining,
          notes: createForm.notes || null,
        })) as { id?: number } | null

        if (hasIssueRange && result?.id) {
          try {
            const rangeMatch = createForm.issues.trim().match(/^(\d+)-(\d+)$/)
            const isSimpleRange = Boolean(rangeMatch) && Number(rangeMatch![1]) === 1

            if (isSimpleRange) {
              const requestedLastRead = Number(createForm.lastIssueRead) || 0
              const lastRead = Math.max(0, Math.min(requestedLastRead, issuesRemaining))
              await issuesApi.migrateThread(result.id, lastRead, issuesRemaining)
            } else {
              const issueListResponse = await issuesApi.create(result.id, createForm.issues.trim())
              const requestedLastRead = Number(createForm.lastIssueRead) || 0
              const lastRead = Math.max(
                0,
                Math.min(requestedLastRead, issueListResponse.issues.length),
              )
              if (lastRead > 0 && issueListResponse.issues.length > 0) {
                const issuesToMark = issueListResponse.issues.slice(0, lastRead)
                await Promise.all(issuesToMark.map((issue) => issuesApi.markRead(issue.id)))
              }
            }
          } catch (issueError: unknown) {
            console.error('Thread created but failed to create issues:', issueError)
            window.alert(
              `Thread created successfully, but failed to create individual issues: ${getApiErrorDetail(issueError)}`,
            )
          }
        }

        setCreateForm(DEFAULT_CREATE_STATE)
        closeCreateModal()
        await onCreated()
      } catch (error: unknown) {
        console.error('Failed to create thread:', error)
        window.alert(`Failed to create thread: ${getApiErrorDetail(error)}`)
      }
    },
    [createForm, closeCreateModal, onCreated, submitCreate],
  )

  const handleEditSubmit = useCallback(
    async (event: FormEvent) => {
      event.preventDefault()
      if (!editingThread) return
      try {
        const data: {
          title: string
          format: string
          notes: string | null
          issues_remaining?: number
        } = {
          title: editForm.title,
          format: editForm.format,
          notes: editForm.notes || null,
        }
        if (editingThread.total_issues === null) {
          data.issues_remaining = Number(editForm.issuesRemaining)
        }
        await submitEdit({ id: editingThread.id, data })
        closeEditModal()
        await onUpdated()
      } catch {
        console.error('Failed to update thread')
      }
    },
    [editingThread, editForm, closeEditModal, onUpdated, submitEdit],
  )

  const handleReactivateSubmit = useCallback(
    async (event: FormEvent) => {
      event.preventDefault()
      if (!reactivateThreadId) return
      try {
        await submitReactivate({
          thread_id: Number(reactivateThreadId),
          issues_to_add: Number(issuesToAdd),
        })
        setOpenModal(null)
        setReactivateThreadId('')
        setIssuesToAdd(1)
        await onReactivated()
      } catch {
        console.error('Failed to reactivate thread')
      }
    },
    [reactivateThreadId, issuesToAdd, onReactivated, submitReactivate],
  )

  const handleMigrationComplete = useCallback(
    async (migratedThread: Thread) => {
      try {
        await onUpdated()
        await refetchSession()
      } catch (error) {
        console.error('Failed to refresh data after migration:', error)
        window.alert('Failed to refresh data. Please refresh the page.')
      }
      setShowMigrationDialog(false)
      setThreadToMigrate(null)
      setEditingThread(migratedThread)
    },
    [onUpdated, refetchSession],
  )

  const handleMigrationSkip = useCallback(() => {
    setShowMigrationDialog(false)
    setThreadToMigrate(null)
  }, [])

  const isAnyModalOpen = useMemo(
    () => openModal !== null || showMigrationDialog,
    [openModal, showMigrationDialog],
  )

  return {
    openModal,
    isAnyModalOpen,
    createForm,
    editForm,
    issuePreview,
    issueParseError,
    editingThread,
    repositioningThread,
    dependencyThread,
    threadToMigrate,
    showMigrationDialog,
    reactivateThreadId,
    issuesToAdd,
    setCreateForm,
    setEditForm,
    setReactivateThreadId,
    setIssuesToAdd,
    showCreateModal,
    closeCreateModal,
    showEditModal,
    closeEditModal,
    openReactivateModal,
    closeReactivateModal,
    openRepositionModal,
    closeRepositionModal,
    openDependenciesModal,
    closeDependenciesModal,
    openMigrationDialog,
    closeMigrationDialog,
    handleCreateSubmit,
    handleEditSubmit,
    handleReactivateSubmit,
    handleMigrationComplete,
    handleMigrationSkip,
    isPendingCreate,
    isPendingEdit,
  }
}
