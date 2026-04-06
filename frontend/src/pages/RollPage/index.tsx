import { useEffect, useMemo, useCallback, useState } from 'react'
import type { ChangeEvent, FormEvent, KeyboardEvent } from 'react'
import LazyDice3D from '../../components/LazyDice3D'
import Modal from '../../components/Modal'
import Tooltip from '../../components/Tooltip'
import MigrationDialog from '../../components/MigrationDialog'
import SimpleMigrationDialog from '../../components/SimpleMigrationDialog'
import CollectionDialog from '../../components/CollectionDialog'
import CollectionToolbar from '../../components/CollectionToolbar'
import { useNavigate } from 'react-router-dom'
import { DICE_LADDER } from '../../components/diceLadder'
import { useSession } from '../../hooks/useSession'
import { useStaleThreads, useThreads } from '../../hooks/useThread'
import { useCollections } from '../../contexts/CollectionContext'
import {
  useClearManualDie,
  useDismissPending,
  useOverrideRoll,
  useRoll,
  useSetDie,
} from '../../hooks/useRoll'
import { useSnooze, useUnsnooze } from '../../hooks/useSnooze'
import { useMoveToBack, useMoveToFront } from '../../hooks/useQueue'
import { useRate } from '../../hooks'
import { threadsApi, dependenciesApi } from '../../services/api'
import { reviewsApi } from '../../services/api-reviews'
import { getApiErrorStatus, getApiErrorDetail } from '../../utils/apiError'
import { isDiceSide } from '../../components/diceTypes'
import type { Thread, RollResponse, SessionThread, Collection, ReviewCreatePayload, Review } from '../../types'
import { useRollPageState } from './useRollPageState'
import type { RatingThread, ThreadMetadata } from './types'
import {
  RATING_THRESHOLD,
  createExplosion,
  buildRatingThread,
} from './utils'
import { RatingView } from './components/RatingView'
import { ThreadPool } from './components/ThreadPool'
import ReviewForm from '../../components/ReviewForm'

export default function RollPage() {
  const state = useRollPageState()
  const {
    isRolling, setIsRolling,
    rolledResult, setRolledResult,
    selectedThreadId, setSelectedThreadId,
    currentDie, setCurrentDie,
    diceState, setDiceState,
    staleThread, setStaleThread,
    staleThreadCount, setStaleThreadCount,
    isOverrideOpen, setIsOverrideOpen,
    overrideThreadId, setOverrideThreadId,
    overrideErrorMessage, setOverrideErrorMessage,
    snoozedExpanded, setSnoozedExpanded,
    blockedExpanded, setBlockedExpanded,
    isDieModalOpen, setIsDieModalOpen,
    selectedThread, setSelectedThread,
    isActionSheetOpen, setIsActionSheetOpen,
    activeRatingThread, setActiveRatingThread,
    isCollectionDialogOpen, setIsCollectionDialogOpen,
    blockingReasonMap, setBlockingReasonMap,
    showMigrationDialog, setShowMigrationDialog,
    threadToMigrate, setThreadToMigrate,
    showSimpleMigration, setShowSimpleMigration,
    isRatingView, setIsRatingView,
    rating, setRating,
    predictedDie, setPredictedDie,
    errorMessage, setErrorMessage,
    suppressPendingAutoOpenRef,
    rollIntervalRef,
    rollTimeoutRef,
  } = state

  const [editingCollection, setEditingCollection] = useState<Collection | null>(null)
  const [showReviewForm, setShowReviewForm] = useState(false)
  const [reviewSaveError, setReviewSaveError] = useState<string | null>(null)
  const [pendingRatingAction, setPendingRatingAction] = useState<{finishSession: boolean} | null>(null)
  const [existingReview, setExistingReview] = useState<Review | null>(null)

  const { data: session, refetch: refetchSession, isPending: isSessionLoading, isError: isSessionError, error: sessionError } = useSession()
  const { activeCollectionId = null } = useCollections()
  const { data: threads, refetch: refetchThreads } = useThreads('', activeCollectionId)
  const { data: staleThreads } = useStaleThreads(7)
  const navigate = useNavigate()

  useEffect(() => {
    if (isSessionError && sessionError) {
      const status = getApiErrorStatus(sessionError)
      if (status === 401) navigate('/login')
    }
  }, [isSessionError, sessionError, navigate])

useEffect(() => {
  const handleTestEditCollection = ((e: CustomEvent<Collection>) => {
    setEditingCollection(e.detail)
    setIsCollectionDialogOpen(true)
  }) as EventListener

  window.addEventListener('test-edit-collection', handleTestEditCollection)
  return () => window.removeEventListener('test-edit-collection', handleTestEditCollection)
}, [setIsCollectionDialogOpen])

  const setDieMutation = useSetDie()
  const clearManualDieMutation = useClearManualDie()
  const rollMutation = useRoll()
  const dismissPendingMutation = useDismissPending()
  const overrideMutation = useOverrideRoll()
  const snoozeMutation = useSnooze()
  const unsnoozeMutation = useUnsnooze()
  const moveToFrontMutation = useMoveToFront()
  const moveToBackMutation = useMoveToBack()
  const rateMutation = useRate()

  async function handleUnsnooze(threadId: number) {
    try {
      await unsnoozeMutation.mutate(threadId)
      await refetchSession()
    } catch (error) {
      console.error('Unsnooze failed:', error)
    }
  }

  async function handleReadStale() {
    if (!staleThread) return
    try {
      const response = await threadsApi.setPending(staleThread.id)
      const threadMetadata: ThreadMetadata = {
        id: response.thread_id, title: response.title, format: response.format,
        issues_remaining: response.issues_remaining, queue_position: response.queue_position,
        total_issues: response.total_issues, reading_progress: response.reading_progress ?? null,
        issue_id: response.issue_id, issue_number: response.issue_number,
        next_issue_id: response.next_issue_id, next_issue_number: response.next_issue_number,
        last_rolled_result: response.result ?? response.last_rolled_result,
      }
      if (response.total_issues === null) {
        setThreadToMigrate(threadMetadata as RatingThread)
        setShowMigrationDialog(true)
      } else {
        enterRatingView(response.thread_id, response.result, threadMetadata)
      }
    } catch (error) {
      console.error('Failed to set pending thread:', error)
    }
  }

  function handleThreadClick(thread: Thread) {
    setSelectedThread(thread)
    setIsActionSheetOpen(true)
  }

const enterRatingView = useCallback(async (threadId: number | null, result: number | null = null, threadMetadata: ThreadMetadata | null = null) => {
  if (threadId) setSelectedThreadId(threadId)
  if (result !== null) setRolledResult(result)

  const ratingThread = buildRatingThread(threadId, result, threadMetadata, session?.active_thread)
  if (ratingThread) {
    setActiveRatingThread(ratingThread)
  } else if (!threadId && session?.active_thread) {
    setActiveRatingThread({
      id: session.active_thread.id, title: session.active_thread.title,
      format: session.active_thread.format,
      issues_remaining: session.active_thread.issues_remaining ?? 0,
      queue_position: session.active_thread.queue_position ?? 0,
      total_issues: session.active_thread.total_issues ?? null,
      reading_progress: session.active_thread.reading_progress ?? null,
      issue_id: session.active_thread.issue_id ?? null,
      issue_number: session.active_thread.issue_number ?? null,
      next_issue_id: session.active_thread.next_issue_id ?? null,
      next_issue_number: session.active_thread.next_issue_number ?? null,
      last_rolled_result: session.active_thread.last_rolled_result ?? null,
    })
  }

  setRating(3.0)
  setErrorMessage('')
  const die = currentDie || 6
  const idx = DICE_LADDER.indexOf(die)
  setPredictedDie(idx > 0 ? DICE_LADDER[idx - 1] : DICE_LADDER[0])
  setIsRatingView(true)
  suppressPendingAutoOpenRef.current = false

  // Fetch existing review if re-rating a thread
  if (threadId) {
    try {
      const token = localStorage.getItem('auth_token') || (window as any).__COMIC_PILE_ACCESS_TOKEN
      if (token) {
        const reviewsResponse = await fetch('/api/v1/reviews/', {
          headers: { 'Authorization': `Bearer ${token}` },
        })
        if (reviewsResponse.ok) {
          const reviewsData = await reviewsResponse.json()
          const existing = reviewsData.reviews?.find((r: Review) => 
            r.thread_id === threadId && 
            (!ratingThread?.issue_number || r.issue_number === ratingThread.issue_number)
          )
          setExistingReview(existing || null)
        }
      }
    } catch (error) {
      console.error('Failed to fetch existing review:', error)
      setExistingReview(null)
    }
  } else {
    setExistingReview(null)
  }
}, [session, currentDie, suppressPendingAutoOpenRef, setSelectedThreadId, setRolledResult, setActiveRatingThread, setRating, setErrorMessage, setPredictedDie, setIsRatingView])

const handleMigrationComplete = useCallback((migratedThread: Thread) => {
  refetchThreads()
  refetchSession()
  setShowMigrationDialog(false)
  setThreadToMigrate(null)
  enterRatingView(migratedThread.id, null, migratedThread)
}, [refetchThreads, refetchSession, enterRatingView, setShowMigrationDialog, setThreadToMigrate])

const handleMigrationSkip = useCallback(() => {
  setShowMigrationDialog(false)
  if (threadToMigrate) enterRatingView(threadToMigrate.id, null, threadToMigrate)
}, [threadToMigrate, enterRatingView, setShowMigrationDialog])

const handleMigrationClose = useCallback(() => {
  setShowMigrationDialog(false)
  setThreadToMigrate(null)
}, [setShowMigrationDialog, setThreadToMigrate])

const handleSimpleMigrationComplete = useCallback((issueNumber: string) => {
    if (!activeRatingThread) return
    setShowSimpleMigration(false)
    rateMutation.mutate({
      thread_id: activeRatingThread.id,
      rating,
      finish_session: false,
      issue_number: issueNumber,
    }).then(() => {
      suppressPendingAutoOpenRef.current = true
      setIsRolling(false)
      setIsRatingView(false)
      setRolledResult(null)
      setSelectedThreadId(null)
      setActiveRatingThread(null)
      setErrorMessage('')
      Promise.allSettled([refetchSession(), refetchThreads()])
    }).catch((error: unknown) => {
      setErrorMessage(getApiErrorDetail(error) || 'Failed to save rating')
    })
  }, [activeRatingThread, rating, rateMutation, refetchSession, refetchThreads, setShowSimpleMigration, suppressPendingAutoOpenRef, setIsRolling, setIsRatingView, setRolledResult, setSelectedThreadId, setActiveRatingThread, setErrorMessage])

  async function handleAction(action: string) {
    if (!selectedThread) return
    setIsActionSheetOpen(false)
    const isSnoozed = session?.snoozed_threads?.some((t) => t.id === selectedThread.id) ?? false

    try {
      switch (action) {
case 'read': {
      const response = await threadsApi.setPending(selectedThread.id)
      const threadMetadata: ThreadMetadata = {
        id: response.thread_id, title: response.title, format: response.format,
        issues_remaining: response.issues_remaining, queue_position: response.queue_position,
        total_issues: response.total_issues, reading_progress: response.reading_progress ?? null,
        issue_id: response.issue_id, issue_number: response.issue_number,
        next_issue_id: response.next_issue_id, next_issue_number: response.next_issue_number,
        last_rolled_result: response.result ?? response.last_rolled_result,
      }
      if (response.total_issues === null) {
        setThreadToMigrate(threadMetadata as RatingThread)
        setShowMigrationDialog(true)
      } else {
        suppressPendingAutoOpenRef.current = true
        enterRatingView(response.thread_id, response.result, threadMetadata)
      }
      break
    }
        case 'move-front':
          await moveToFrontMutation.mutate(selectedThread.id)
          await refetchSession()
          await refetchThreads()
          break
        case 'move-back':
          await moveToBackMutation.mutate(selectedThread.id)
          await refetchSession()
          await refetchThreads()
          break
        case 'snooze':
          if (isSnoozed) {
            await unsnoozeMutation.mutate(selectedThread.id)
          } else {
            await snoozeMutation.mutate()
          }
          await refetchSession()
          await refetchThreads()
          break
        case 'edit':
          navigate('/queue', { state: { editThreadId: selectedThread.id } })
          break
      }
    } catch (error) {
      console.error('Action failed:', error)
    }
  }

  const snoozedIds = useMemo(() => new Set(session?.snoozed_threads?.map((t) => t.id) ?? []), [session?.snoozed_threads])
  const activeThreads = useMemo(() => threads?.filter((t) => t.status === 'active' && !t.is_blocked && !snoozedIds.has(t.id)) ?? [], [threads, snoozedIds])
  const blockedThreads = useMemo(() => threads?.filter((t) => t.status === 'active' && t.is_blocked) ?? [], [threads])
  const displayDie = isDiceSide(currentDie) ? currentDie : 6

useEffect(() => {
  const fetchBlockingReasons = async () => {
    if (!blockedThreads.length) {
      setBlockingReasonMap({})
      return
    }
    const details: Array<[number, string[]]> = await Promise.all(
      blockedThreads.map(async (thread) => {
        try {
          const info = await dependenciesApi.getBlockingInfo(thread.id)
          return [thread.id, info.blocking_reasons || []]
        } catch { return [thread.id, []] }
      })
    )
    setBlockingReasonMap(Object.fromEntries(details))
  }
  fetchBlockingReasons()
}, [blockedThreads, setBlockingReasonMap])

useEffect(() => {
  if (session?.current_die) setCurrentDie(session.current_die)
  if (session?.last_rolled_result !== undefined && session?.last_rolled_result !== null) {
    setRolledResult(session.last_rolled_result)
  }
}, [session?.current_die, session?.last_rolled_result, setCurrentDie, setRolledResult])

  useEffect(() => {
    if (suppressPendingAutoOpenRef.current) return
    const pendingThreadId = session?.pending_thread_id
    if (!pendingThreadId) return

    const pendingId = Number(pendingThreadId)
    const isCurrentPendingSelection = Number(selectedThreadId) === pendingId
    const hasHydratedPendingMetadata = Boolean(activeRatingThread?.title)

    if (isRatingView && isCurrentPendingSelection && hasHydratedPendingMetadata) return

    const pendingFromSession = session?.active_thread && session.active_thread.id === pendingId
      ? { id: session.active_thread.id, title: session.active_thread.title, format: session.active_thread.format,
          issues_remaining: session.active_thread.issues_remaining ?? 0, queue_position: session.active_thread.queue_position ?? 0,
          total_issues: session.active_thread.total_issues ?? null, reading_progress: session.active_thread.reading_progress ?? null,
          last_rolled_result: session.last_rolled_result ?? session.active_thread.last_rolled_result ?? null }
      : null

    const pendingFromThreads = !pendingFromSession && activeThreads.length > 0
      ? activeThreads.find((t) => t.id === pendingId) : null

    const pendingResult = pendingFromSession?.last_rolled_result ?? session?.last_rolled_result ?? null
    const pendingMetadata = (pendingFromSession ?? pendingFromThreads) as ThreadMetadata | null
    const shouldInitializeRatingView = !isRatingView || !isCurrentPendingSelection

    setSelectedThreadId(pendingId)
    if (pendingResult !== null && pendingResult !== undefined) setRolledResult(pendingResult)
    if (pendingMetadata && pendingMetadata.title) {
        setActiveRatingThread({
          id: pendingMetadata.id ?? pendingId, title: pendingMetadata.title, format: pendingMetadata.format ?? '',
          issues_remaining: pendingMetadata.issues_remaining ?? 0, queue_position: pendingMetadata.queue_position ?? 0,
          issue_id: pendingMetadata.issue_id ?? null, issue_number: pendingMetadata.issue_number ?? null,
          next_issue_id: pendingMetadata.next_issue_id ?? null, next_issue_number: pendingMetadata.next_issue_number ?? null,
          total_issues: pendingMetadata.total_issues ?? null, reading_progress: pendingMetadata.reading_progress ?? null,
        last_rolled_result: pendingMetadata.last_rolled_result ?? pendingResult,
      })
    }
    if (shouldInitializeRatingView) {
      setRating(3.0)
      setErrorMessage('')
      const die = currentDie || 6
      const idx = DICE_LADDER.indexOf(die)
      setPredictedDie(idx > 0 ? DICE_LADDER[idx - 1] : DICE_LADDER[0])
      setIsRatingView(true)
    }
  }, [session?.pending_thread_id, session?.active_thread, session?.last_rolled_result, activeThreads, activeRatingThread, currentDie, isRatingView, selectedThreadId, suppressPendingAutoOpenRef, setSelectedThreadId, setRolledResult, setActiveRatingThread, setRating, setErrorMessage, setPredictedDie, setIsRatingView])

useEffect(() => {
  const actionable = staleThreads?.filter(t => !t.is_blocked) ?? []
  if (actionable.length > 0) {
    const thread = actionable[0]
    const lastActivity = thread.last_activity_at ? new Date(thread.last_activity_at) : new Date(thread.created_at)
    const diffDays = Math.floor((Date.now() - lastActivity.getTime()) / (1000 * 60 * 60 * 24))
    setStaleThread(diffDays >= 7 ? { ...thread, days: diffDays } : null)
    setStaleThreadCount(actionable.filter(t => {
      const activity = t.last_activity_at ? new Date(t.last_activity_at) : new Date(t.created_at)
      const days = Math.floor((Date.now() - activity.getTime()) / (1000 * 60 * 60 * 24))
      return days >= 7
    }).length)
  } else {
    setStaleThread(null)
    setStaleThreadCount(0)
  }
}, [staleThreads, setStaleThread, setStaleThreadCount])

useEffect(() => {
  return () => {
    if (rollIntervalRef.current) clearInterval(rollIntervalRef.current)
    if (rollTimeoutRef.current) clearTimeout(rollTimeoutRef.current)
  }
}, [rollIntervalRef, rollTimeoutRef])

  function updateRatingUI(val: string) {
    const num = parseFloat(val)
    setRating(num)
    let newPredictedDie = currentDie
    const idx = DICE_LADDER.indexOf(currentDie)
    if (num >= RATING_THRESHOLD) {
      newPredictedDie = idx > 0 ? DICE_LADDER[idx - 1] : DICE_LADDER[0]
    } else {
      newPredictedDie = idx < DICE_LADDER.length - 1 ? DICE_LADDER[idx + 1] : DICE_LADDER[DICE_LADDER.length - 1]
    }
    setPredictedDie(newPredictedDie)
  }

  async function handleSubmitRating(finishSession = false) {
    if (rating >= RATING_THRESHOLD) createExplosion()

    const freshTotalIssues =
      session?.active_thread?.id === activeRatingThread?.id
        ? session?.active_thread?.total_issues ?? activeRatingThread?.total_issues
        : activeRatingThread?.total_issues

    if (activeRatingThread && freshTotalIssues === null) {
      setShowSimpleMigration(true)
      return
    }
    
    // Show review form instead of immediately submitting rating
    setPendingRatingAction({ finishSession })
    setShowReviewForm(true)
  }

  async function handleReviewSubmit(reviewData: ReviewCreatePayload) {
    if (!activeRatingThread) return
    
    // Function to return to roll view - batch all state updates together
    const returnToRollView = () => {
      setShowReviewForm(false)
      setIsRatingView(false)
      setPendingRatingAction(null)
      setIsRolling(false)
      setRolledResult(null)
      setSelectedThreadId(null)
      setActiveRatingThread(null)
      setErrorMessage('')
    }

    try {
      const finishSession = pendingRatingAction?.finishSession || false
      
      // Submit the rating with review data first
      await rateMutation.mutate({ 
        thread_id: activeRatingThread.id, 
        rating, 
        finish_session: finishSession,
        issue_number: activeRatingThread.issue_number || undefined
      })
      
      // Submit the review if text was provided
      let reviewSaveError = null
      if (reviewData.review_text?.trim()) {
        try {
          await reviewsApi.createOrUpdateReview(reviewData)
          setReviewSaveError(null)
        } catch (reviewError) {
          console.error('Failed to save review:', reviewError)
          reviewSaveError = 'Your rating was saved. The review text failed to save — try again or skip.'
          setReviewSaveError(reviewSaveError)
        }
      }

      // Refresh data
      const refreshResults = await Promise.allSettled([refetchSession(), refetchThreads()])
      if (refreshResults[0].status === 'rejected' || refreshResults[1].status === 'rejected') {
        setErrorMessage('Rating saved but failed to refresh. Please refresh the page.')
        returnToRollView()
        return
      }
      
      // If review save failed, keep modal open so user can see error and retry
      if (reviewSaveError) {
        return
      }
      
      // Return to roll view after all operations complete successfully
      returnToRollView()
    } catch (error: unknown) {
      setErrorMessage(getApiErrorDetail(error) || 'Failed to save rating')
      // Keep the modal open on rating error so user can see the error and retry
    }
  }

  

  async function handleSnooze() {
    try {
      await snoozeMutation.mutate()
      await refetchSession()
      await refetchThreads()
      setIsRolling(false)
      setIsRatingView(false)
      setRolledResult(null)
      setSelectedThreadId(null)
      setActiveRatingThread(null)
    } catch (error: unknown) {
      setErrorMessage(getApiErrorDetail(error) || 'Failed to snooze thread')
    }
  }

  async function handleRefreshThread() {
    await refetchSession()
    await refetchThreads()
  }

  const dieSize = currentDie || 6
  const filteredThreads = activeThreads.filter(t => !isRatingView || t.id !== (selectedThreadId ? Number(selectedThreadId) : null))
  const pool = filteredThreads.slice(0, dieSize)
  const hasValidRolledResult = Number.isInteger(rolledResult) && rolledResult !== null && rolledResult >= 1 && rolledResult <= currentDie

  async function handleSetDie(die: number) {
    setCurrentDie(die)
    await setDieMutation.mutate(die)
  }

  async function handleClearManualDie() {
    await clearManualDieMutation.mutate()
  }

  async function recoverPendingRollConflict() {
    const latestSession = await refetchSession()
    const pendingId = Number(latestSession?.pending_thread_id ?? session?.pending_thread_id ?? 0)
    if (!pendingId) return false
    const pendingMetadata = latestSession?.active_thread && latestSession.active_thread.id === pendingId
      ? latestSession.active_thread : activeThreads.find((t) => t.id === pendingId)
    enterRatingView(pendingId, latestSession?.last_rolled_result ?? session?.last_rolled_result ?? null, pendingMetadata)
    return true
  }

  function handleRoll() {
    if (isRolling) return
    if (session?.pending_thread_id && !suppressPendingAutoOpenRef.current) {
      const pendingId = Number(session.pending_thread_id)
      const pendingMetadata = session?.active_thread && session.active_thread.id === pendingId
        ? session.active_thread : activeThreads.find((t) => t.id === pendingId)
      enterRatingView(pendingId, session?.last_rolled_result ?? null, pendingMetadata)
      return
    }

    if (suppressPendingAutoOpenRef.current && session?.pending_thread_id) {
      suppressPendingAutoOpenRef.current = false
    }

    if (rollIntervalRef.current) clearInterval(rollIntervalRef.current)
    if (rollTimeoutRef.current) clearTimeout(rollTimeoutRef.current)

    setIsRolling(true)
    setDiceState('idle')

    let currentRollCount = 0
    rollIntervalRef.current = setInterval(() => {
      currentRollCount++
      if (currentRollCount >= 10) {
        clearInterval(rollIntervalRef.current!)
        rollIntervalRef.current = null
        rollTimeoutRef.current = setTimeout(async () => {
          rollTimeoutRef.current = null
          try {
            const response = await rollMutation.mutate()
            enterRatingView(response.thread_id, response.result, response)
            setIsRolling(false)
          } catch (error: unknown) {
            const status = getApiErrorStatus(error)
            const detail = getApiErrorDetail(error)
            if (status === 409) {
              const recovered = await recoverPendingRollConflict()
              if (!recovered) setErrorMessage(detail || 'A roll is already pending. Rate, snooze, or cancel it before rolling again.')
              setIsRolling(false)
              return
            }
            console.error('Roll failed:', error)
            setErrorMessage(detail || 'Failed to roll')
            setIsRolling(false)
          }
        }, 400)
      }
    }, 80)
  }

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      handleRoll()
    }
  }



  function handleOverrideSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!overrideThreadId) return
    overrideMutation.mutate({ thread_id: Number(overrideThreadId) }).then((response) => {
      setIsOverrideOpen(false)
      setOverrideThreadId('')
      setOverrideErrorMessage('')
      enterRatingView(response.thread_id, response.result, response)
    }).catch((error: unknown) => {
      setOverrideErrorMessage(getApiErrorDetail(error) || 'Failed to override roll')
    })
  }

  if (isSessionLoading && !isSessionError) {
    return <div className="text-center py-10 text-stone-500 font-black uppercase tracking-widest text-[10px]">Loading...</div>
  }

  if (isSessionError || !session) {
    const errorDetail = getApiErrorDetail(sessionError)
    const status = getApiErrorStatus(sessionError)
    return (
      <div className="min-h-screen flex flex-col items-center justify-center p-4">
        <div className="text-center space-y-4">
          <div className="text-4xl">⚠️</div>
          <h2 className="text-xl font-black text-stone-300 uppercase tracking-wider">Session Error</h2>
          <p className="text-sm text-stone-400">{errorDetail}</p>
          {status === 401 ? (
            <button onClick={() => navigate('/login')} className="px-4 py-2 bg-amber-600/20 border border-amber-600/50 rounded-lg text-xs font-black uppercase tracking-widest text-amber-500 hover:bg-amber-600/30 transition-colors">
              Go to Login
            </button>
          ) : (
            <button onClick={() => refetchSession()} className="px-4 py-2 bg-amber-600/20 border border-amber-600/50 rounded-lg text-xs font-black uppercase tracking-widest text-amber-500 hover:bg-amber-600/30 transition-colors">
              Retry
            </button>
          )}
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen flex flex-col">
      <header className="flex justify-between items-center px-3 py-2 shrink-0 z-10">
        <div>
          <h1 className="text-2xl font-black tracking-tighter text-glow uppercase">Pile Roller</h1>
          {((session?.snoozed_threads?.length ?? 0) > 0) && currentDie === 20 && (
            <div className="flex items-center gap-2 mt-1">
              <span className="text-[9px] text-stone-500 uppercase tracking-wider">pool at max size (d20) - snoozing won't increase it further</span>
            </div>
          )}
          {((session?.snoozed_threads?.length ?? 0) > 0) && currentDie !== 20 && (
            <div className="flex items-center gap-2 mt-1">
              <Tooltip content="Snoozed offset"><span className="modifier-badge text-[10px] font-black text-amber-500 cursor-help border-b border-dashed border-stone-600">+{session?.snoozed_threads?.length ?? 0}</span></Tooltip>
              <Tooltip content="Snoozed offset active"><span className="text-[9px] text-stone-500 uppercase tracking-wider cursor-help border-b border-dashed border-stone-600">offset active</span></Tooltip>
            </div>
          )}
        </div>
        <div className="flex items-center gap-2">
          <div id="die-selector">
            <div className="hidden md:flex gap-2">
              {DICE_LADDER.map((die) => (
                <button key={die} onClick={() => handleSetDie(die)} disabled={setDieMutation.isPending}
                  className={`die-btn px-2 py-1 text-[10px] font-black rounded-lg border transition-colors ${die === currentDie ? 'bg-amber-600/20 border-amber-600 text-amber-500' : 'bg-white/5 border-white/10 hover:bg-white/10'}`}>
                  d{die}
                </button>
              ))}
              <button onClick={handleClearManualDie} disabled={clearManualDieMutation.isPending}
                className={`px-2 py-1 text-[10px] font-black rounded-lg border transition-colors ${session.manual_die ? 'bg-amber-500/20 border-amber-500 text-amber-400' : 'bg-white/5 border-white/10 hover:bg-white/10'}`}
                title={session.manual_die ? `Exit manual mode (currently d${session.manual_die})` : 'Return to automatic dice ladder mode'}>
                Auto
              </button>
            </div>
            <div className="md:hidden">
              <button onClick={() => setIsDieModalOpen(true)} disabled={setDieMutation.isPending}
                className="px-3 py-1 text-[10px] font-black rounded-lg border bg-amber-600/20 border-amber-600 text-amber-500 transition-colors">
                d{currentDie}
              </button>
            </div>
          </div>
          <div className="flex items-center gap-2 px-3 py-1 bg-white/5 rounded-xl border border-white/10 shrink-0">
            <div className="relative flex items-center justify-center" style={{ width: '40px', height: '40px' }}>
              <div className="w-full h-full">
                <LazyDice3D sides={displayDie} value={1} isRolling={false} showValue={false} color={0xffffff} />
              </div>
            </div>
            <div className="text-right">
              <Tooltip content="Dice ladder: d4→d6→d8→d10→d12→d20. Promotes automatically based on ratings (5→up, 1-2→down)">
                <span className="block text-[8px] font-black text-stone-500 uppercase tracking-wider cursor-help border-b border-dashed border-stone-600">Ladder</span>
              </Tooltip>
              <span id="header-die-label" className="text-[10px] font-black text-amber-500">d{currentDie}</span>
            </div>
          </div>
          <Tooltip content="Manually select a thread to override the next roll result.">
            <button type="button" onClick={() => setIsOverrideOpen(true)} className="px-3 py-2 bg-white/5 border border-white/10 text-stone-300 rounded-xl text-[10px] font-black uppercase tracking-widest hover:bg-white/10 transition-all">
              Override
            </button>
          </Tooltip>
        </div>
      </header>
      <CollectionToolbar onNewCollection={() => setIsCollectionDialogOpen(true)} />

      <div className="flex-1 flex flex-col min-h-0">
        <div className="glass-card flex-1 flex flex-col relative">
          <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-80 h-80 bg-amber-900/10 rounded-full blur-[120px] pointer-events-none"></div>
          <div className="flex-1 flex flex-col">
            {!isRatingView ? (
              <div id="main-die-3d" onClick={handleRoll} onKeyDown={handleKeyDown} role="button" tabIndex={0} aria-label="Roll the dice"
                className={`dice-state-${diceState} relative z-10 cursor-pointer shrink-0 flex items-center justify-center rounded-full transition-all mt-4 mx-auto`}
                style={{ width: '200px', height: '200px' }}
                data-testid="main-die-3d">
                <div className="w-full h-full main-die-optical-center">
                  <LazyDice3D sides={displayDie} value={rolledResult || 1} isRolling={isRolling} showValue={false} color={0xffffff}
                    onRollComplete={() => setDiceState('rolled')} />
                </div>
              </div>
            ) : (
              <RatingView
                activeRatingThread={activeRatingThread}
                currentDie={currentDie}
                rolledResult={rolledResult}
                rating={rating}
                predictedDie={predictedDie}
                hasValidRolledResult={hasValidRolledResult}
                poolSize={pool.length}
                errorMessage={errorMessage}
                rateIsPending={rateMutation.isPending}
                snoozeIsPending={snoozeMutation.isPending}
                dismissIsPending={dismissPendingMutation.isPending}
                onUpdateRating={updateRatingUI}
                onSubmitRating={handleSubmitRating}
                onSnooze={handleSnooze}
                onRefreshThread={handleRefreshThread}
                onCancel={async () => {
                  try {
                    await dismissPendingMutation.mutate()
                    await refetchSession()
                    await refetchThreads()
                  } catch (error) {
                    setErrorMessage(getApiErrorDetail(error) || 'Failed to cancel pending roll')
                    return
                  }
                  setIsRatingView(false)
                  setRolledResult(null)
                  setSelectedThreadId(null)
                  setActiveRatingThread(null)
                  setErrorMessage('')
                }}
              />
            )}

  <ThreadPool
    pool={pool}
    blockedThreads={blockedThreads}
    blockingReasonMap={blockingReasonMap}
    isRatingView={isRatingView}
    isRolling={isRolling}
    rolledResult={rolledResult}
    selectedThreadId={selectedThreadId}
    staleThread={staleThread}
    staleThreadCount={staleThreadCount}
    snoozedThreads={session?.snoozed_threads || []}
    snoozedExpanded={snoozedExpanded}
    blockedExpanded={blockedExpanded}
    onThreadClick={handleThreadClick}
    onUnsnooze={handleUnsnooze}
    onReadStale={handleReadStale}
    onToggleSnoozed={() => setSnoozedExpanded(!snoozedExpanded)}
    onToggleBlocked={() => setBlockedExpanded(!blockedExpanded)}
    unsnoozeIsPending={unsnoozeMutation.isPending}
  />
          </div>
        </div>

        <div id="explosion-layer" className="explosion-wrap"></div>

        {isCollectionDialogOpen && <CollectionDialog collection={editingCollection} onClose={() => { setIsCollectionDialogOpen(false); setEditingCollection(null) }} />}

        {showMigrationDialog && threadToMigrate && (
          <MigrationDialog thread={threadToMigrate} onComplete={handleMigrationComplete} onSkip={handleMigrationSkip} onClose={handleMigrationClose} />
        )}

        {showSimpleMigration && activeRatingThread && (
          <SimpleMigrationDialog threadTitle={activeRatingThread.title} onComplete={handleSimpleMigrationComplete} onClose={() => setShowSimpleMigration(false)} />
        )}

        <Modal isOpen={isOverrideOpen} title="Override Roll" onClose={() => { setIsOverrideOpen(false); setOverrideErrorMessage('') }}>
          <form className="space-y-4" onSubmit={handleOverrideSubmit}>
            <p className="text-xs text-stone-400">Pick a thread to force next roll result.</p>
            <div className="space-y-2">
              <label className="text-[10px] font-bold uppercase tracking-widest text-stone-500">Thread</label>
              <select value={overrideThreadId} onChange={(event) => setOverrideThreadId(event.target.value)}
                className="w-full bg-white/5 border border-white/10 rounded-xl px-3 py-2 text-sm text-stone-300" required>
                <option value="">Select a thread...</option>
                <optgroup label="Active Threads">
                  {activeThreads.map((thread) => (<option key={thread.id} value={thread.id}>{thread.title} ({thread.format})</option>))}
                </optgroup>
                {(session?.snoozed_threads?.length ?? 0) > 0 && (
                  <optgroup label="Snoozed Threads">
                {session?.snoozed_threads?.map((thread) => (<option key={thread.id} value={thread.id}>{thread.title} ({thread.format})</option>))}
                  </optgroup>
                )}
              </select>
            </div>
            {overrideErrorMessage && (
              <p className="text-xs text-red-400">{overrideErrorMessage}</p>
            )}
            <button type="submit" disabled={overrideMutation.isPending || !overrideThreadId}
              className="w-full py-3 glass-button text-xs font-black uppercase tracking-widest disabled:opacity-60">
              {overrideMutation.isPending ? 'Overriding...' : 'Override Roll'}
            </button>
          </form>
        </Modal>

        <Modal isOpen={isDieModalOpen} title="Select Die" onClose={() => setIsDieModalOpen(false)}>
          <div className="grid grid-cols-3 gap-2">
            {DICE_LADDER.map((die) => (
              <button key={die} onClick={async () => { try { await handleSetDie(die); setIsDieModalOpen(false) } catch (error) { console.error('Failed to set die:', error) }}}
                disabled={setDieMutation.isPending}
                className={`px-3 py-3 text-sm font-black rounded-lg border transition-colors ${die === currentDie ? 'bg-amber-600/20 border-amber-600 text-amber-500' : 'bg-white/5 border-white/10 hover:bg-white/10'}`}>
                d{die}
              </button>
            ))}
            <button onClick={async () => { try { await handleClearManualDie(); setIsDieModalOpen(false) } catch (error) { console.error('Failed to clear manual die:', error) }}}
              disabled={clearManualDieMutation.isPending}
              className={`px-3 py-3 text-sm font-black rounded-lg border transition-colors ${session.manual_die ? 'bg-amber-500/20 border-amber-500 text-amber-400' : 'bg-white/5 border-white/10 hover:bg-white/10'}`}>
              Auto
            </button>
          </div>
        </Modal>

        <Modal isOpen={isActionSheetOpen} title={selectedThread?.title ?? ''} onClose={() => setIsActionSheetOpen(false)}>
          <div className="space-y-2">
            <button type="button" onClick={() => handleAction('read')} className="w-full py-3 px-4 bg-white/5 border border-white/10 rounded-xl text-left text-sm font-black text-stone-300 hover:bg-white/10 transition-all flex items-center gap-3">
              <span className="text-lg">📖</span><span>Read Now</span>
            </button>
            <button type="button" onClick={() => handleAction('move-front')} className="w-full py-3 px-4 bg-white/5 border border-white/10 rounded-xl text-left text-sm font-black text-stone-300 hover:bg-white/10 transition-all flex items-center gap-3">
              <span className="text-lg">⬆️</span><span>Move to Front</span>
            </button>
            <button type="button" onClick={() => handleAction('move-back')} className="w-full py-3 px-4 bg-white/5 border border-white/10 rounded-xl text-left text-sm font-black text-stone-300 hover:bg-white/10 transition-all flex items-center gap-3">
              <span className="text-lg">⬇️</span><span>Move to Back</span>
            </button>
            <button type="button" onClick={() => handleAction('snooze')} className="w-full py-3 px-4 bg-white/5 border border-white/10 rounded-xl text-left text-sm font-black text-stone-300 hover:bg-white/10 transition-all flex items-center gap-3">
              <span className="text-lg">{session?.snoozed_threads?.some((t) => t.id === selectedThread?.id) ? '🔔' : '😴'}</span>
              <span>{session?.snoozed_threads?.some((t) => t.id === selectedThread?.id) ? 'Unsnooze' : 'Snooze'}</span>
            </button>
            <button type="button" onClick={() => handleAction('edit')} className="w-full py-3 px-4 bg-white/5 border border-white/10 rounded-xl text-left text-sm font-black text-stone-300 hover:bg-white/10 transition-all flex items-center gap-3">
              <span className="text-lg">✏️</span><span>Edit Thread</span>
            </button>
          </div>
        </Modal>

        {showReviewForm && activeRatingThread && (
          <ReviewForm
            isOpen={showReviewForm}
            onClose={() => {
              setShowReviewForm(false)
              setIsRatingView(false)
              setPendingRatingAction(null)
              setReviewSaveError(null)
              setErrorMessage('')
              setExistingReview(null)
            }}
            onSubmit={handleReviewSubmit}
            threadId={activeRatingThread.id}
            threadTitle={activeRatingThread.title}
            issueNumber={activeRatingThread.issue_number || undefined}
            rating={rating}
            error={reviewSaveError}
            existingReview={existingReview}
          />
        )}
      </div>
    </div>
  )
}
