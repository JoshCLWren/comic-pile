import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import type { Thread, ThreadListItem, ThreadCreatePayload } from '../../types'
import { getManualCreatorCreditList } from '../../types'
import { issuesApi } from '../../services/api-issues'
import { useBugReportRestore } from '../../contexts/useBugReportRestore'
import { useToast } from '../../contexts/useToast'
import { getApiErrorDetail } from '../../utils/apiError'
import { DEFAULT_CREATE_STATE, type EditThreadData, type QueueFormState } from './types'
import type { ParsedIssueRangeDetail } from '../../utils/issueParser'

type ModalKey = 'create' | 'edit' | 'reactivate' | 'dependency' | 'reposition' | 'migration' | 'addSeriesComicVine'

interface QueueModalsParams {
  threads: ThreadListItem[] | null | undefined
  onCreated: () => Promise<void>
  onUpdated: () => Promise<void>
  onReactivated: () => Promise<void>
  refetchSession: () => Promise<void>
  submitCreate: (input: ThreadCreatePayload) => Promise<{ id?: number }>
  submitEdit: (input: {
    id: number
    data: EditThreadData
  }) => Promise<Thread>
  submitReactivate: (input: {
    thread_id: number
    issues_to_add: number
  }) => Promise<Thread>
  isPendingCreate: boolean
  isPendingEdit: boolean
  showRollNudge: boolean
  onDismissRollNudge: () => void
  onRollNudgeNavigate: () => void
}

interface UseQueueModalsResult {
  openModal: ModalKey | null
  isAnyModalOpen: boolean
  createForm: QueueFormState
  editForm: QueueFormState
  /** Failure feedback rendered inside the open Add Series dialog. */
  createError: string | null
  issuePreview: number | null
  issueParseError: string | null
  issueParseWarnings: string[]
  issueParseBreakdown: ParsedIssueRangeDetail['breakdown']
  editingThread: Thread | ThreadListItem | null
  repositioningThread: ThreadListItem | null
  dependencyThread: ThreadListItem | null
  threadToMigrate: Thread | ThreadListItem | null
  showMigrationDialog: boolean
  reactivateThreadId: string
  issuesToAdd: number
  setCreateForm: (next: QueueFormState) => void
  setEditForm: (next: QueueFormState) => void
  setReactivateThreadId: (next: string) => void
  setIssuesToAdd: (next: number) => void
  showCreateModal: () => void
  closeCreateModal: () => void
  showEditModal: (thread: ThreadListItem) => void
  closeEditModal: () => void
  markIssuesLoaded: () => void
  openReactivateModal: (thread: ThreadListItem | null) => void
  closeReactivateModal: () => void
  openRepositionModal: (thread: ThreadListItem) => void
  closeRepositionModal: () => void
  openDependenciesModal: (thread: ThreadListItem) => void
  closeDependenciesModal: () => void
  openMigrationDialog: (thread: Thread | ThreadListItem) => void
  closeMigrationDialog: () => void
  handleCreateSubmit: (event: FormEvent) => Promise<void>
  handleEditSubmit: (event: FormEvent) => Promise<void>
  handleReactivateSubmit: (event: FormEvent) => Promise<void>
  handleMigrationComplete: (migratedThread: Thread) => Promise<void>
  handleMigrationSkip: () => void
  isPendingCreate: boolean
  isPendingEdit: boolean
  isIssuesLoading: boolean
  showRollNudge: boolean
  dismissRollNudge: () => void
  rollNudgeNavigate: () => void
  showAddSeriesComicVineModal: () => void
  closeAddSeriesComicVineModal: () => void
}

/**
 * Injectable seams for hook-level side channels. Production callers omit
 * `deps`; tests substitute a toast double through the same seam pattern
 * `useQueueThreadActions` uses.
 */
export interface UseQueueModalsDeps {
  toastHook?: typeof useToast
}

/**
 * Centralized modal lifecycle, restore-action registration, and form state for
 * every modal the Queue page coordinates. The hook returns plain handlers and
 * presentational state so the page can compose the modal modules without
 * re-implementing the navigation, bug-report-restore, or location-state wiring.
 */
export function useQueueModals(params: QueueModalsParams, deps: UseQueueModalsDeps = {}): UseQueueModalsResult {
  const { toastHook = useToast } = deps
  const { showToast } = toastHook()
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
  const [createError, setCreateError] = useState<string | null>(null)
  const [editForm, setEditForm] = useState<QueueFormState>(DEFAULT_CREATE_STATE)
  const [editingThread, setEditingThread] = useState<Thread | ThreadListItem | null>(null)
  const [reactivateThreadId, setReactivateThreadId] = useState('')
  const [issuesToAdd, setIssuesToAdd] = useState(1)
  const [repositioningThread, setRepositioningThread] = useState<ThreadListItem | null>(null)
  const [dependencyThread, setDependencyThread] = useState<ThreadListItem | null>(null)
  const [threadToMigrate, setThreadToMigrate] = useState<Thread | ThreadListItem | null>(null)
  const [showMigrationDialog, setShowMigrationDialog] = useState(false)
  const [issuePreview, setIssuePreview] = useState<number | null>(null)
  const [issueParseError, setIssueParseError] = useState<string | null>(null)
  const [issueParseWarnings, setIssueParseWarnings] = useState<string[]>([])
  const [issueParseBreakdown, setIssueParseBreakdown] = useState<ParsedIssueRangeDetail['breakdown']>([])
  const [isIssuesLoading, setIsIssuesLoading] = useState(false)

  const creatingRef = useRef(false)

  const showRollNudge = params.showRollNudge

  const clearQueueModalState = useCallback(() => {
    navigate(location.pathname, { replace: true, state: {} })
  }, [location.pathname, navigate])

  const showCreateModal = useCallback(() => {
    setCreateForm(DEFAULT_CREATE_STATE)
    setCreateError(null)
    setOpenModal('create')
    setRestoreAction(() => {
      setCreateForm(DEFAULT_CREATE_STATE)
      setCreateError(null)
      setOpenModal('create')
    })
  }, [setRestoreAction])

  const closeCreateModal = useCallback(() => {
    setOpenModal(null)
    setCreateError(null)
    clearRestoreAction()
    clearQueueModalState()
  }, [clearQueueModalState, clearRestoreAction])

  const showEditModal = useCallback(
    (thread: ThreadListItem) => {
      // Only migrated threads render IssueToggleList; its load completion
      // clears this flag. Unmigrated threads never enter the loading state.
      const issuesLoadRequired = thread.total_issues != null
      setEditingThread(thread)
      setEditForm({
        title: thread.title,
        format: thread.format,
        issuesRemaining: thread.issues_remaining,
        notes: thread.notes || '',
        issues: '',
        lastIssueRead: 0,
        manualCreatorCredits: getManualCreatorCreditList(thread),
      })
      setIsIssuesLoading(issuesLoadRequired)
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
          manualCreatorCredits: getManualCreatorCreditList(thread),
        })
        setIsIssuesLoading(issuesLoadRequired)
        setOpenModal('edit')
      })
    },
    [setRestoreAction],
  )

  const closeEditModal = useCallback(() => {
    setEditingThread(null)
    setIsIssuesLoading(false)
    setOpenModal(null)
    clearRestoreAction()
    clearQueueModalState()
  }, [clearQueueModalState, clearRestoreAction])

  const markIssuesLoaded = useCallback(() => {
    setIsIssuesLoading(false)
  }, [])

  const openReactivateModal = useCallback((thread: ThreadListItem | null) => {
    setReactivateThreadId(thread?.id ? String(thread.id) : '')
    setIssuesToAdd(1)
    setOpenModal('reactivate')
  }, [])

  const closeReactivateModal = useCallback(() => {
    setOpenModal(null)
  }, [])

  const openRepositionModal = useCallback((thread: ThreadListItem) => {
    setRepositioningThread(thread)
    setOpenModal('reposition')
  }, [])

  const closeRepositionModal = useCallback(() => {
    setRepositioningThread(null)
    setOpenModal(null)
  }, [])

  const openDependenciesModal = useCallback((thread: ThreadListItem) => {
    setDependencyThread(thread)
    setOpenModal('dependency')
  }, [])

  const closeDependenciesModal = useCallback(() => {
    setDependencyThread(null)
    setOpenModal(null)
  }, [])

  const openMigrationDialog = useCallback((thread: Thread | ThreadListItem) => {
    setThreadToMigrate(thread)
    setShowMigrationDialog(true)
  }, [])

  const closeMigrationDialog = useCallback(() => {
    setShowMigrationDialog(false)
    setThreadToMigrate(null)
  }, [])

  const showAddSeriesComicVineModal = useCallback(() => {
    setOpenModal('addSeriesComicVine')
    setRestoreAction(() => {
      setOpenModal('addSeriesComicVine')
    })
  }, [setRestoreAction])

  const closeAddSeriesComicVineModal = useCallback(() => {
    setOpenModal(null)
    clearRestoreAction()
    clearQueueModalState()
  }, [clearQueueModalState, clearRestoreAction])

  const dismissRollNudge = useCallback(() => {
    params.onDismissRollNudge()
  }, [params])

  const rollNudgeNavigate = useCallback(() => {
    params.onRollNudgeNavigate()
  }, [params])

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
      if (issueInput && issueInput.trim()) {
        try {
          const { parseIssueRangeDetailed, validateIssueRangeForStaging } = await import(
            '../../utils/issueParser'
          )
          // #4161: the preview must mirror the Save gate. `validateIssueRangeForStaging`
          // is the single source of truth: an invalid entry surfaces its error here and
          // never produces a creation count or a "will be created as a literal issue"
          // promise. Accepted entries (including numbered labels such as "2b") preview
          // without warnings.
          const validation = validateIssueRangeForStaging(issueInput)
          if (cancelled) return
          if (!validation.valid) {
            setIssuePreview(null)
            setIssueParseError(validation.error)
            setIssueParseWarnings([])
            setIssueParseBreakdown([])
            return
          }
          const detail = parseIssueRangeDetailed(issueInput)
          setIssuePreview(detail.total)
          setIssueParseError(null)
          setIssueParseWarnings(detail.warnings)
          setIssueParseBreakdown(detail.breakdown)
        } catch (err) {
          if (cancelled) return
          setIssuePreview(null)
          setIssueParseError(err instanceof Error ? err.message : 'Invalid issue range')
          setIssueParseWarnings([])
          setIssueParseBreakdown([])
        }
      } else {
        if (cancelled) return
        setIssuePreview(null)
        setIssueParseError(null)
        setIssueParseWarnings([])
        setIssueParseBreakdown([])
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
      if (creatingRef.current) return
      creatingRef.current = true
      setCreateError(null)
      try {
        const { parseIssueRange, validateIssueRangeForStaging } = await import('../../utils/issueParser')
        const hasIssueRange = Boolean(createForm.issues && createForm.issues.trim())
        if (hasIssueRange) {
          // #3631: block the save when the ISSUES entry is not a valid issue.
          // `validateIssueRangeForStaging` is the single source of truth here: it
          // rejects entries that carry no issue number (e.g. "abc", "-3", "19-")
          // while still accepting numbered labels such as "2b", "1.5", and
          // "1-Annual" that do identify an issue. The preview warnings are a
          // display-only affordance (#3262) and must not block a valid entry.
          const validation = validateIssueRangeForStaging(createForm.issues.trim())
          if (!validation.valid) {
            // Render the rejection inside the open dialog: a toast paints below
            // the modal layer, so on mobile the dialog hides it entirely.
            setCreateError(
              `Failed to create series: ${validation.error ?? 'Invalid issue range.'}`,
            )
            creatingRef.current = false
            return
          }
        }
        let issuesRemaining = Number(createForm.issuesRemaining)
        if (hasIssueRange) {
          issuesRemaining = parseIssueRange(createForm.issues)
        }
        // SAFETY: submitCreate resolves to the created thread record or null when creation is skipped.
        const result = (await submitCreate({
          title: createForm.title,
          format: createForm.format,
          issues_remaining: issuesRemaining,
          notes: createForm.notes ?? null,
          manual_creator_credits: createForm.manualCreatorCredits,
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
                await issuesApi.bulkMarkRead(issuesToMark.map((issue) => issue.id))
              }
            }
          } catch (issueError: unknown) {
            console.error('Thread created but failed to create issues:', issueError)
            showToast(
              `Thread created successfully, but failed to create individual issues: ${getApiErrorDetail(issueError)}`,
              'error',
            )
          }
        }

        setCreateForm(DEFAULT_CREATE_STATE)
        closeCreateModal()
        await onCreated()
      } catch (error: unknown) {
        console.error('Failed to create thread:', error)
        // The Add Series dialog stays open, so the failure reason has to live
        // inside it rather than in a toast the dialog covers.
        setCreateError(`Failed to create series: ${getApiErrorDetail(error)}`)
      } finally {
        creatingRef.current = false
      }
    },
    [createForm, closeCreateModal, onCreated, submitCreate, showToast],
  )

  const handleEditSubmit = useCallback(
    async (event: FormEvent) => {
      event.preventDefault()
      if (!editingThread) return
      try {
        const data: EditThreadData = {
          title: editForm.title,
          format: editForm.format,
          // Send the field verbatim so an emptied Notes field is sent as an
          // explicit clear. Only omitting `notes` leaves the saved value
          // unchanged (issue #3629).
          notes: editForm.notes,
          manual_creator_credits: editForm.manualCreatorCredits,
        }
        if (editingThread.total_issues == null) {
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
        showToast('Failed to refresh data. Please refresh the page.', 'error')
      }
      setShowMigrationDialog(false)
      setThreadToMigrate(null)
      setEditingThread(migratedThread)
    },
    [onUpdated, refetchSession, showToast],
  )

  const handleMigrationSkip = useCallback(() => {
    setShowMigrationDialog(false)
    setThreadToMigrate(null)
  }, [])

  const isAnyModalOpen = useMemo(
    () => openModal !== null || showMigrationDialog || showRollNudge,
    [openModal, showMigrationDialog, showRollNudge],
  )

  return {
    openModal,
    isAnyModalOpen,
    createForm,
    createError,
    editForm,
    issuePreview,
    issueParseError,
    issueParseWarnings,
    issueParseBreakdown,
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
    markIssuesLoaded,
    openReactivateModal,
    closeReactivateModal,
    openRepositionModal,
    closeRepositionModal,
    openDependenciesModal,
    closeDependenciesModal,
    openMigrationDialog,
    closeMigrationDialog,
    showAddSeriesComicVineModal,
    closeAddSeriesComicVineModal,
    handleCreateSubmit,
    handleEditSubmit,
    handleReactivateSubmit,
    handleMigrationComplete,
    handleMigrationSkip,
    isPendingCreate,
    isPendingEdit,
    isIssuesLoading,
    showRollNudge,
    dismissRollNudge,
    rollNudgeNavigate,
  }
}
