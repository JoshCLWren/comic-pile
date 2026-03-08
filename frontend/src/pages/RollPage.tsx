import { useState, useEffect, useMemo, useRef, useCallback } from 'react'
import type { ChangeEvent, FormEvent, KeyboardEvent } from 'react'
import axios from 'axios'
import LazyDice3D from '../components/LazyDice3D'
import Modal from '../components/Modal'
import Tooltip from '../components/Tooltip'
import MigrationDialog from '../components/MigrationDialog'
import SimpleMigrationDialog from '../components/SimpleMigrationDialog'
import CollectionDialog from '../components/CollectionDialog'
import { useNavigate } from 'react-router-dom'
import { DICE_LADDER } from '../components/diceLadder'
import { useSession } from '../hooks/useSession'
import { useStaleThreads, useThreads } from '../hooks/useThread'
import { useCollections } from '../contexts/CollectionContext'
import {
  useClearManualDie,
  useDismissPending,
  useOverrideRoll,
  useRoll,
  useSetDie,
} from '../hooks/useRoll'
import { useSnooze, useUnsnooze } from '../hooks/useSnooze'
import { useMoveToBack, useMoveToFront } from '../hooks/useQueue'
import { useRate } from '../hooks'
import { threadsApi } from '../services/api'
import type { RollResponse, SessionThread, Thread } from '../types'

const RATING_THRESHOLD = 4.0

type RatingThread = Pick<
  Thread,
  'id' | 'title' | 'format' | 'issues_remaining' | 'queue_position' | 'total_issues' | 'reading_progress'
> &
  Pick<SessionThread, 'issue_id' | 'issue_number' | 'next_issue_id' | 'next_issue_number' | 'last_rolled_result'>

type ApiErrorPayload = { detail?: string }
type ApiLikeError = { response?: { status?: number; data?: ApiErrorPayload } }

function getApiErrorStatus(error: unknown): number | null {
  if (axios.isAxiosError(error)) {
    return error.response?.status ?? null
  }
  if (error && typeof error === 'object' && 'response' in error) {
    return (error as ApiLikeError).response?.status ?? null
  }
  return null
}

function getApiErrorDetail(error: unknown): string | null {
  if (axios.isAxiosError<ApiErrorPayload>(error)) {
    return error.response?.data?.detail ?? null
  }
  if (error && typeof error === 'object' && 'response' in error) {
    return (error as ApiLikeError).response?.data?.detail ?? null
  }
  return null
}

function mapSessionThreadToRatingThread(thread: SessionThread): RatingThread {
  return {
    id: thread.id,
    title: thread.title,
    format: thread.format,
    issues_remaining: thread.issues_remaining ?? 0,
    queue_position: thread.queue_position ?? 0,
    total_issues: thread.total_issues ?? null,
    reading_progress: thread.reading_progress ?? null,
    issue_id: thread.issue_id ?? null,
    issue_number: thread.issue_number ?? null,
    next_issue_id: thread.next_issue_id ?? null,
    next_issue_number: thread.next_issue_number ?? null,
    last_rolled_result: thread.last_rolled_result ?? null,
  }
}

export default function RollPage() {
  const [isRolling, setIsRolling] = useState(false)
  const [rolledResult, setRolledResult] = useState<number | null>(null)
  const [selectedThreadId, setSelectedThreadId] = useState<number | null>(null)
  const [currentDie, setCurrentDie] = useState(6)
  const [diceState, setDiceState] = useState('idle')
  const [staleThread, setStaleThread] = useState<(Thread & { days: number }) | null>(null)
  const [isOverrideOpen, setIsOverrideOpen] = useState(false)
  const [overrideThreadId, setOverrideThreadId] = useState('')
  const [snoozedExpanded, setSnoozedExpanded] = useState(false)
  const [isDieModalOpen, setIsDieModalOpen] = useState(false)
  const [selectedThread, setSelectedThread] = useState<Thread | null>(null)
  const [isActionSheetOpen, setIsActionSheetOpen] = useState(false)
  const [activeRatingThread, setActiveRatingThread] = useState<RatingThread | null>(null)
  const [isCollectionDialogOpen, setIsCollectionDialogOpen] = useState(false)

  // Migration state
  const [showMigrationDialog, setShowMigrationDialog] = useState(false)
  const [threadToMigrate, setThreadToMigrate] = useState<RatingThread | null>(null)
  const [showSimpleMigration, setShowSimpleMigration] = useState(false)

  // Rating state
  const [isRatingView, setIsRatingView] = useState(false)
  const [rating, setRating] = useState(4.0)
  const [predictedDie, setPredictedDie] = useState(6)
  const [errorMessage, setErrorMessage] = useState('')

  const rollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const rollTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const suppressPendingAutoOpenRef = useRef(false)

  const { data: session, refetch: refetchSession, isPending: isSessionLoading, isError: isSessionError, error: sessionError } = useSession()
  const {
    collections = [],
    activeCollectionId = null,
    setActiveCollectionId,
    isLoading: isCollectionsLoading = false,
  } = useCollections()
  const { data: threads, refetch: refetchThreads } = useThreads('', activeCollectionId)
  const { data: staleThreads } = useStaleThreads(7)

  const navigate = useNavigate()

  // Handle session API errors - redirect to login on 401
  useEffect(() => {
    if (isSessionError && sessionError) {
      const status = getApiErrorStatus(sessionError)
      if (status === 401) {
        navigate('/login')
      }
    }
  }, [isSessionError, sessionError, navigate])

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
    if (!staleThread) {
      return
    }
    try {
      const response = await threadsApi.setPending(staleThread.id)
      const threadMetadata = {
        id: response.thread_id,
        title: response.title,
        format: response.format,
        issues_remaining: response.issues_remaining,
        queue_position: response.queue_position,
        total_issues: response.total_issues,
        reading_progress: response.reading_progress ?? null,
      }
      
      // Check if thread needs migration
      if (!response.total_issues) {
        setThreadToMigrate(threadMetadata)
        setShowMigrationDialog(true)
      } else {
        enterRatingView(response.thread_id, response.result, response)
      }
    } catch (error) {
      console.error('Failed to set pending thread:', error)
    }
  }

  function handleThreadClick(thread: Thread) {
    setSelectedThread(thread)
    setIsActionSheetOpen(true)
  }

  const enterRatingView = useCallback((threadId: number | null, result: number | null = null, threadMetadata: Partial<RollResponse & SessionThread> | null = null) => {
    suppressPendingAutoOpenRef.current = false

    if (threadId) setSelectedThreadId(threadId)
    if (result !== null) setRolledResult(result)

    if (threadMetadata && threadMetadata.title) {
      setActiveRatingThread({
        id: threadMetadata.id ?? threadMetadata.thread_id ?? Number(threadId),
        title: threadMetadata.title,
        format: threadMetadata.format,
        issues_remaining: threadMetadata.issues_remaining,
        queue_position: threadMetadata.queue_position,
        issue_id: threadMetadata.issue_id ?? null,
        issue_number: threadMetadata.issue_number ?? null,
        next_issue_id: threadMetadata.next_issue_id ?? null,
        next_issue_number: threadMetadata.next_issue_number ?? null,
        total_issues: threadMetadata.total_issues ?? null,
        reading_progress: threadMetadata.reading_progress ?? null,
        last_rolled_result:
          threadMetadata.result ?? threadMetadata.last_rolled_result ?? result ?? null,
      })
    } else if (!threadId && session?.active_thread) {
      setActiveRatingThread(mapSessionThreadToRatingThread(session.active_thread))
    } else if (session?.active_thread && session.active_thread.id === Number(threadId)) {
      setActiveRatingThread(mapSessionThreadToRatingThread(session.active_thread))
    }

    setRating(4.0)
    setErrorMessage('')

    const die = currentDie || 6
    const idx = DICE_LADDER.indexOf(die)
    const initialPredicted = idx > 0 ? DICE_LADDER[idx - 1] : DICE_LADDER[0]

    setPredictedDie(initialPredicted)
    setIsRatingView(true)
  }, [session, currentDie])

  const handleMigrationComplete = useCallback((migratedThread: Thread) => {
    refetchThreads()
    refetchSession()
    setShowMigrationDialog(false)
    setThreadToMigrate(null)
    // Proceed to rating
    enterRatingView(migratedThread.id, null, migratedThread)
  }, [refetchThreads, refetchSession, enterRatingView])

  const handleMigrationSkip = useCallback(() => {
    setShowMigrationDialog(false)
    // Proceed with old system rating
    if (threadToMigrate) {
      enterRatingView(threadToMigrate.id, null, threadToMigrate)
    }
  }, [threadToMigrate, enterRatingView])

  const handleMigrationClose = useCallback(() => {
    setShowMigrationDialog(false)
    setThreadToMigrate(null)
  }, [])

  const handleSimpleMigrationComplete = useCallback((issueNumber: string) => {
    const num = parseInt(issueNumber, 10)
    setShowSimpleMigration(false)
    
    rateMutation.mutate({
      rating,
      issues_read: 1,
      finish_session: false,
      issue_number: num
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
      const detail = getApiErrorDetail(error)
      setErrorMessage(detail || 'Failed to save rating')
    })
  }, [rating, rateMutation, refetchSession, refetchThreads])

  async function handleAction(action: string) {
    if (!selectedThread) return

    setIsActionSheetOpen(false)

    const isSnoozed = session?.snoozed_threads?.some((t) => t.id === selectedThread.id) ?? false

    try {
      switch (action) {
        case 'read':
          {
            const response = await threadsApi.setPending(selectedThread.id)
            const threadMetadata = {
              id: response.thread_id,
              title: response.title,
              format: response.format,
              issues_remaining: response.issues_remaining,
              queue_position: response.queue_position,
              total_issues: response.total_issues,
              reading_progress: response.reading_progress ?? null,
              last_rolled_result: response.result ?? response.last_rolled_result ?? null,
            }
            
            // Check if thread needs migration
            if (!response.total_issues) {
              setThreadToMigrate(threadMetadata)
              setShowMigrationDialog(true)
            } else {
              enterRatingView(response.thread_id, response.result, threadMetadata)
            }
          }
          break
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
            await threadsApi.setPending(selectedThread.id)
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
  const activeThreads = useMemo(
    () => threads?.filter((thread) => thread.status === 'active' && !thread.is_blocked) ?? [],
    [threads],
  )

  useEffect(() => {
    if (session?.current_die) {
      setCurrentDie(session.current_die)
    }
    if (session?.last_rolled_result !== undefined && session?.last_rolled_result !== null) {
      setRolledResult(session.last_rolled_result)
    }
  }, [session?.current_die, session?.last_rolled_result])

  useEffect(() => {
    if (suppressPendingAutoOpenRef.current) return

    const pendingThreadId = session?.pending_thread_id
    if (!pendingThreadId) return

    const pendingId = Number(pendingThreadId)
    const isCurrentPendingSelection = Number(selectedThreadId) === pendingId
    const hasHydratedPendingMetadata = Boolean(activeRatingThread?.title)

    if (isRatingView && isCurrentPendingSelection && hasHydratedPendingMetadata) return

    const pendingFromSession =
      session?.active_thread && session.active_thread.id === pendingId
        ? {
          id: session.active_thread.id,
          title: session.active_thread.title,
          format: session.active_thread.format,
          issues_remaining: session.active_thread.issues_remaining,
          queue_position: session.active_thread.queue_position,
          last_rolled_result:
            session.last_rolled_result ?? session.active_thread.last_rolled_result ?? null,
        }
        : null

    const pendingFromThreads =
      !pendingFromSession && activeThreads.length > 0
        ? activeThreads.find((thread) => thread.id === pendingId)
        : null

    const pendingResult = pendingFromSession?.last_rolled_result ?? session?.last_rolled_result ?? null
    const pendingMetadata =
      (pendingFromSession ?? pendingFromThreads) as Partial<RollResponse & RatingThread> | null
    const shouldInitializeRatingView = !isRatingView || !isCurrentPendingSelection

    setSelectedThreadId(pendingId)
    if (pendingResult !== null && pendingResult !== undefined) {
      setRolledResult(pendingResult)
    }
    if (pendingMetadata && pendingMetadata.title) {
      setActiveRatingThread({
        id: pendingMetadata.id ?? pendingId,
        title: pendingMetadata.title,
        format: pendingMetadata.format,
        issues_remaining: pendingMetadata.issues_remaining,
        queue_position: pendingMetadata.queue_position,
        issue_id: pendingMetadata.issue_id ?? null,
        issue_number: pendingMetadata.issue_number ?? null,
        next_issue_id: pendingMetadata.next_issue_id ?? null,
        next_issue_number: pendingMetadata.next_issue_number ?? null,
        total_issues: pendingMetadata.total_issues ?? null,
        reading_progress: pendingMetadata.reading_progress ?? null,
        last_rolled_result: pendingMetadata.last_rolled_result ?? pendingResult,
      })
    }
    if (shouldInitializeRatingView) {
      setRating(4.0)
      setErrorMessage('')
      const die = currentDie || 6
      const idx = DICE_LADDER.indexOf(die)
      setPredictedDie(idx > 0 ? DICE_LADDER[idx - 1] : DICE_LADDER[0])
      setIsRatingView(true)
    }
  }, [
    session?.pending_thread_id,
    session?.active_thread,
    session?.last_rolled_result,
    activeThreads,
    activeRatingThread,
    currentDie,
    isRatingView,
    selectedThreadId,
  ])
  useEffect(() => {
    if (staleThreads && staleThreads.length > 0) {
      const thread = staleThreads[0]
      const lastActivity = thread.last_activity_at ? new Date(thread.last_activity_at) : new Date(thread.created_at)
      const diffMs = Date.now() - lastActivity.getTime()
      const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24))

      if (diffDays >= 7) {
        setStaleThread({ ...thread, days: diffDays })
      } else {
        setStaleThread(null)
      }
    } else {
      setStaleThread(null)
    }
  }, [staleThreads])

  useEffect(() => {
    // Cleanup timers on unmount
    return () => {
      if (rollIntervalRef.current) {
        clearInterval(rollIntervalRef.current)
      }
      if (rollTimeoutRef.current) {
        clearTimeout(rollTimeoutRef.current)
      }
    }
  }, [])

  function updateRatingUI(val: string) {
    const num = parseFloat(val)
    setRating(num)
    let newPredictedDie = currentDie

    if (num >= RATING_THRESHOLD) {
      const idx = DICE_LADDER.indexOf(currentDie)
      if (idx > 0) {
        newPredictedDie = DICE_LADDER[idx - 1]
      } else {
        newPredictedDie = DICE_LADDER[0]
      }
    } else {
      const idx = DICE_LADDER.indexOf(currentDie)
      if (idx < DICE_LADDER.length - 1) {
        newPredictedDie = DICE_LADDER[idx + 1]
      } else {
        newPredictedDie = DICE_LADDER[DICE_LADDER.length - 1]
      }
    }

    setPredictedDie(newPredictedDie)
  }

  function createExplosion() {
    const layer = document.getElementById('explosion-layer');
    if (!layer) return;
    const count = 50;

    for (let i = 0; i < count; i++) {
      const p = document.createElement('div');
      p.className = 'particle';
      const angle = Math.random() * Math.PI * 2;
      const dist = 150 + Math.random() * 250;
      p.style.left = '50%';
      p.style.top = '50%';
      p.style.setProperty('--tx', Math.cos(angle) * dist + 'px');
      p.style.setProperty('--ty', Math.sin(angle) * dist + 'px');
      p.style.background = i % 2 ? 'var(--accent-red)' : 'var(--accent-amber)';
      layer.appendChild(p);
      setTimeout(() => p.remove(), 1000);
    }
  }

  async function handleSubmitRating(finishSession = false) {
    if (rating >= RATING_THRESHOLD) {
      createExplosion();
    }

    if (activeRatingThread && !activeRatingThread.total_issues) {
      setShowSimpleMigration(true)
      return
    }

    try {
      await rateMutation.mutate({
        rating,
        issues_read: 1,
        finish_session: finishSession
      });

      suppressPendingAutoOpenRef.current = true
      setIsRolling(false)
      setIsRatingView(false);
      setRolledResult(null);
      setSelectedThreadId(null);
      setActiveRatingThread(null);
      setErrorMessage('');

      const refreshResults = await Promise.allSettled([refetchSession(), refetchThreads()])
      const [sessionRefreshResult, threadsRefreshResult] = refreshResults
      if (sessionRefreshResult.status === 'rejected') {
        console.error('Failed to refresh session after rating:', sessionRefreshResult.reason)
      }
      if (threadsRefreshResult.status === 'rejected') {
        console.error('Failed to refresh threads after rating:', threadsRefreshResult.reason)
      }
    } catch (error: unknown) {
      const detail = getApiErrorDetail(error)
      setErrorMessage(detail || 'Failed to save rating');
    }
  }

  async function handleSnooze() {
    try {
      await snoozeMutation.mutate();
      await refetchSession();
      await refetchThreads();
      setIsRolling(false)
      setIsRatingView(false);
      setRolledResult(null);
      setSelectedThreadId(null);
      setActiveRatingThread(null);
    } catch (error: unknown) {
      const detail = getApiErrorDetail(error)
      setErrorMessage(detail || 'Failed to snooze thread');
    }
  }

  const dieSize = currentDie || 6;
  // P3: Filter pool using local selectedThreadId state for immediate consistency
  const filteredThreads = activeThreads.filter(t =>
    !isRatingView || t.id !== (selectedThreadId ? Number(selectedThreadId) : null)
  );
  const pool = filteredThreads.slice(0, dieSize) || [];
  const hasValidRolledResult =
    Number.isInteger(rolledResult) && rolledResult >= 1 && rolledResult <= currentDie

  // Compute visual queue position from sorted array index (DB positions may have gaps)
  const ratingThreadVisualPosition = activeRatingThread
    ? activeThreads.findIndex(t => t.id === activeRatingThread.id) + 1 || activeRatingThread.queue_position
    : null

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

    if (!pendingId) {
      return false
    }

    const pendingMetadata =
      latestSession?.active_thread && latestSession.active_thread.id === pendingId
        ? latestSession.active_thread
        : activeThreads.find((thread) => thread.id === pendingId)

    enterRatingView(
      pendingId,
      latestSession?.last_rolled_result ?? session?.last_rolled_result ?? null,
      pendingMetadata,
    )
    return true
  }

  function handleRoll() {
    if (isRolling) return
    if (session?.pending_thread_id && !suppressPendingAutoOpenRef.current) {
      const pendingId = Number(session.pending_thread_id)
      const pendingMetadata =
        session?.active_thread && session.active_thread.id === pendingId
          ? session.active_thread
          : activeThreads.find((thread) => thread.id === pendingId)
      enterRatingView(pendingId, session?.last_rolled_result ?? null, pendingMetadata)
      return
    }

    // Ignore stale pending state once immediately after Save & Continue.
    // The backend clears pending now, so this only guards against stale client session data.
    const ignorePendingOnce = suppressPendingAutoOpenRef.current && session?.pending_thread_id
    if (ignorePendingOnce) {
      suppressPendingAutoOpenRef.current = false
    }

    if (rollIntervalRef.current) {
      clearInterval(rollIntervalRef.current)
    }
    if (rollTimeoutRef.current) {
      clearTimeout(rollTimeoutRef.current)
    }

    setIsRolling(true)
    setDiceState('idle')

    let currentRollCount = 0
    const maxRolls = 10

    rollIntervalRef.current = setInterval(() => {
      currentRollCount++

      if (currentRollCount >= maxRolls) {
        clearInterval(rollIntervalRef.current)
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
              if (!recovered) {
                setErrorMessage(
                  detail ||
                    'A roll is already pending. Rate, snooze, or cancel it before rolling again.',
                )
              }
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

  function getProgressPercentage(
    thread: { total_issues?: number | null; issues_remaining?: number | null } | null,
  ) {
    if (!thread || !thread.total_issues) return 0
    const readCount = thread.total_issues - (thread.issues_remaining || 0)
    return Math.round((readCount / thread.total_issues) * 100)
  }

  const handleRollComplete = useCallback(() => {
    setDiceState('rolled')
  }, [])

  function handleCollectionChange(event: ChangeEvent<HTMLSelectElement>) {
    const value = event.target.value
    setActiveCollectionId(value === 'all' ? null : Number(value))
  }

  function handleOverrideSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!overrideThreadId) return

    overrideMutation
      .mutate({ thread_id: Number(overrideThreadId) })
      .then((response) => {
        setIsOverrideOpen(false)
        setOverrideThreadId('')
        enterRatingView(response.thread_id, response.result, response)
      })
      .catch(() => {
        // Handle error if needed
      })
  }

  // Show loading state only when loading and no error
  if (isSessionLoading && !isSessionError) {
    return <div className="text-center py-10 text-stone-500 font-black uppercase tracking-widest text-[10px]">Loading...</div>
  }

  // Show error state when session API fails
  if (isSessionError || !session) {
    const errorDetail = getApiErrorDetail(sessionError) || sessionError?.message || 'Failed to load session'
    const status = getApiErrorStatus(sessionError)

    return (
      <div className="min-h-screen flex flex-col items-center justify-center p-4">
        <div className="text-center space-y-4">
          <div className="text-4xl">⚠️</div>
          <h2 className="text-xl font-black text-stone-300 uppercase tracking-wider">Session Error</h2>
          <p className="text-sm text-stone-400">{errorDetail}</p>
          {status === 401 ? (
            <button
              onClick={() => navigate('/login')}
              className="px-4 py-2 bg-amber-600/20 border border-amber-600/50 rounded-lg text-xs font-black uppercase tracking-widest text-amber-500 hover:bg-amber-600/30 transition-colors"
            >
              Go to Login
            </button>
          ) : (
            <button
              onClick={() => refetchSession()}
              className="px-4 py-2 bg-amber-600/20 border border-amber-600/50 rounded-lg text-xs font-black uppercase tracking-widest text-amber-500 hover:bg-amber-600/30 transition-colors"
            >
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
          {session?.snoozed_threads?.length > 0 && (
            <div className="flex items-center gap-2 mt-1">
              <span className="modifier-badge text-[10px] font-black text-amber-500">+{session.snoozed_threads.length}</span>
              <span className="text-[9px] text-stone-500 uppercase tracking-wider">snoozed offset active</span>
            </div>
          )}
        </div>
        <div className="flex items-center gap-2">
          <div id="die-selector">
            <div className="hidden md:flex gap-2">
              {DICE_LADDER.map((die) => (
                <button
                  key={die}
                  onClick={() => handleSetDie(die)}
                  disabled={setDieMutation.isPending}
                  className={`die-btn px-2 py-1 text-[10px] font-black rounded-lg border transition-colors ${die === currentDie
                    ? 'bg-amber-600/20 border-amber-600 text-amber-500'
                    : 'bg-white/5 border-white/10 hover:bg-white/10'
                    }`}
                >
                  d{die}
                </button>
              ))}
              <button
                onClick={handleClearManualDie}
                disabled={clearManualDieMutation.isPending}
                className={`px-2 py-1 text-[10px] font-black rounded-lg border transition-colors ${session.manual_die
                  ? 'bg-amber-500/20 border-amber-500 text-amber-400'
                  : 'bg-white/5 border-white/10 hover:bg-white/10'
                  }`}
                title={session.manual_die ? `Exit manual mode (currently d${session.manual_die})` : 'Return to automatic dice ladder mode'}
              >
                Auto
              </button>
            </div>
            <div className="md:hidden">
              <button
                onClick={() => setIsDieModalOpen(true)}
                disabled={setDieMutation.isPending}
                className="px-3 py-1 text-[10px] font-black rounded-lg border bg-amber-600/20 border-amber-600 text-amber-500 transition-colors"
              >
                d{currentDie}
              </button>
            </div>
          </div>
          <div className="flex items-center gap-2 px-3 py-1 bg-white/5 rounded-xl border border-white/10 shrink-0">
            <div className="relative flex items-center justify-center" style={{ width: '40px', height: '40px' }}>
              <div className="w-full h-full">
                <LazyDice3D sides={currentDie} value={1} isRolling={false} showValue={false} color={0xffffff} />
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
            <button
              type="button"
              onClick={() => setIsOverrideOpen(true)}
              className="px-3 py-2 bg-white/5 border border-white/10 text-stone-300 rounded-xl text-[10px] font-black uppercase tracking-widest hover:bg-white/10 transition-all"
            >
              Override
            </button>
          </Tooltip>
        </div>
      </header>

      <div className="flex-1 flex flex-col min-h-0">
        <div className="glass-card flex-1 flex flex-col relative">
          <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-80 h-80 bg-amber-900/10 rounded-full blur-[120px] pointer-events-none"></div>

          <div className="flex-1 flex flex-col">
            {!isRatingView ? (
              <div
                id="main-die-3d"
                onClick={handleRoll}
                onKeyDown={handleKeyDown}
                role="button"
                tabIndex={0}
                aria-label="Roll the dice"
                className={`dice-state-${diceState} relative z-10 cursor-pointer shrink-0 flex items-center justify-center rounded-full transition-all mt-4 mx-auto`}
                style={{ width: '200px', height: '200px' }}
              >
                <div className="w-full h-full main-die-optical-center">
                  <LazyDice3D
                    sides={currentDie}
                    value={rolledResult || 1}
                    isRolling={isRolling}
                    showValue={false}
                    color={0xffffff}
                    onRollComplete={handleRollComplete}
                  />
                </div>
              </div>
            ) : (
              <div className="p-4 space-y-8 relative z-10">
                <div id="thread-info" role="status" aria-live="polite">
                  <div className="space-y-3 text-center">
                    {activeRatingThread?.issue_number ? (
                      <>
                        <h2 className="text-2xl font-black text-stone-200">{activeRatingThread?.title || 'Loading...'}</h2>
                        <div className="flex items-center justify-center gap-3 flex-wrap">
                          <span className="bg-amber-500/20 text-amber-300 px-3 py-1 rounded-lg text-sm font-black uppercase tracking-[0.2em] border border-amber-500/20">
                            #{activeRatingThread.issue_number}
                          </span>
                          {activeRatingThread.total_issues && (
                            <span className="text-stone-400 text-xs font-bold">
                              (#{activeRatingThread.issue_number} of {activeRatingThread.total_issues})
                            </span>
                          )}
                          <span className="bg-amber-600/20 text-amber-400 px-3 py-1 rounded-lg text-[10px] font-black uppercase tracking-[0.2em] border border-amber-600/20">
                            Queue #{ratingThreadVisualPosition ?? '-'}
                          </span>
                        </div>
                      </>
                    ) : (
                      <>
                        <h2 className="text-2xl font-black text-stone-200">{activeRatingThread?.title || 'Loading...'}</h2>
                        <div className="flex items-center justify-center gap-3">
                          <span className="bg-amber-600/20 text-amber-400 px-3 py-1 rounded-lg text-[10px] font-black uppercase tracking-[0.2em] border border-amber-600/20">
                            Queue #{ratingThreadVisualPosition ?? '-'}
                          </span>
                          <span className="bg-red-800/20 text-red-600 px-3 py-1 rounded-lg text-[10px] font-black uppercase tracking-[0.2em] border border-red-800/20">
                            {activeRatingThread?.format || '...'}
                          </span>
                          <span className="text-stone-500 text-xs font-bold">{activeRatingThread?.issues_remaining || 0} Issues left</span>
                        </div>
                      </>
                    )}
                    {activeRatingThread?.reading_progress && activeRatingThread?.total_issues && (
                      <div className="reading-progress max-w-md mx-auto">
                        <div className="h-3 bg-white/10 rounded-full overflow-hidden">
                          <div 
                            className="h-full bg-amber-600 transition-all duration-300"
                            style={{
                              width: `${getProgressPercentage(activeRatingThread)}%`
                            }}
                          />
                        </div>
                        <span className="mt-1 block text-[10px] text-stone-400 font-bold uppercase tracking-wider">
                          {activeRatingThread.reading_progress === 'completed' ? 'Completed' : 'In Progress'}
                        </span>
                      </div>
                    )}
                  </div>
                </div>

                <div className="space-y-8">
                  <div id="rating-preview-dice" className="dice-perspective">
                    <div
                      id="die-preview-wrapper"
                      className="dice-state-rate-flow relative flex items-center justify-center"
                      style={{ width: '120px', height: '120px', margin: '0 auto' }}
                    >
                      <LazyDice3D
                        sides={currentDie}
                        value={rolledResult || 1}
                        isRolling={false}
                        showValue={false}
                        freeze
                        color={0xffffff}
                      />
                    </div>
                    {hasValidRolledResult && (
                      <p className="mt-6 text-[10px] font-black uppercase tracking-[0.2em] text-stone-400 text-center">
                        Rolled {rolledResult} on d{currentDie}
                      </p>
                    )}
                  </div>

                  <div className="text-center space-y-4">
                    <Tooltip content={`Ratings of ${RATING_THRESHOLD.toFixed(1)}+ move the thread to the front and step the die down. Lower ratings move it back and step the die up.`}>
                      <p className="text-[10px] font-black uppercase tracking-[0.4em] text-stone-500 cursor-help">How was it?</p>
                    </Tooltip>
                    <div id="rating-value" className={`text-4xl font-black ${rating >= RATING_THRESHOLD ? 'text-amber-500' : 'text-red-700'}`}>
                      {rating.toFixed(1)}
                    </div>
                    <input
                      type="range"
                      id="rating-input"
                      name="rating"
                      min="0.5"
                      max="5.0"
                      step="0.5"
                      value={rating}
                      className="w-full h-4"
                      aria-label="Rating from 0.5 to 5.0 in steps of 0.5"
                      onChange={(e) => updateRatingUI(e.target.value)}
                    />
                  </div>

                  <div
                    className={`p-4 rounded-3xl border shadow-xl ${rating >= RATING_THRESHOLD
                      ? 'bg-amber-600/5 border-amber-600/20'
                      : 'bg-red-800/5 border-red-800/20'
                      }`}
                  >
                    <p id="queue-effect" className="text-[10px] font-black text-stone-300 text-center uppercase tracking-[0.15em] leading-relaxed">
                      {rating >= RATING_THRESHOLD
                        ? `Excellent! Die steps down 🎲 Move to front${predictedDie !== currentDie ? ` (d${predictedDie})` : ''}`
                        : `Okay. Die steps up 🎲 Move to back${predictedDie !== currentDie ? ` (d${predictedDie})` : ''}`}
                    </p>
                  </div>

                  <div className="space-y-3">
                    <button
                      type="button"
                      onClick={() => handleSubmitRating(false)}
                      disabled={rateMutation.isPending}
                      className="w-full py-3 bg-white/5 hover:bg-white/10 border border-white/10 rounded-xl text-[10px] font-black uppercase tracking-[0.2em] transition-all disabled:opacity-50"
                    >
                      {rateMutation.isPending ? 'Saving...' : 'Save & Continue'}
                    </button>
                    <button
                      type="button"
                      onClick={handleSnooze}
                      disabled={snoozeMutation.isPending}
                      className="w-full py-4 glass-button text-sm font-black uppercase tracking-[0.2em] relative shadow-[0_15px_40px_rgba(20,184,166,0.3)] disabled:opacity-50"
                    >
                      {snoozeMutation.isPending ? 'Snoozing...' : 'Snooze'}
                    </button>
                    <div className="flex justify-center">
                      <button
                        type="button"
                        onClick={async () => {
                          try {
                            await dismissPendingMutation.mutate()
                            await refetchSession()
                            await refetchThreads()
                          } catch (error) {
                            setErrorMessage(
                              getApiErrorDetail(error) || 'Failed to cancel pending roll',
                            )
                            return
                          }
                          setIsRatingView(false)
                          setRolledResult(null)
                          setSelectedThreadId(null)
                          setActiveRatingThread(null)
                          setErrorMessage('')
                        }}
                        className="px-4 py-2 text-[10px] font-bold uppercase tracking-widest text-stone-500 hover:text-stone-300 hover:bg-white/5 border border-transparent hover:border-white/10 rounded-lg transition-all"
                      >
                        Cancel Pending Roll
                      </button>
                    </div>
                  </div>

                  {errorMessage && (
                    <div id="error-message" className="text-[10px] text-rose-500 text-center font-bold">
                      {errorMessage}
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Shared Pool Display */}
            <div className={`px-4 pb-4 flex flex-col ${!isRatingView ? 'flex-1 min-h-[300px]' : 'border-t border-white/5 pt-8'}`}>
              {!isRolling && rolledResult === null && !isRatingView && (
                <p
                  id="tap-instruction"
                  className="text-stone-500 font-black uppercase tracking-[0.5em] text-[10px] animate-pulse shrink-0 text-center mb-8"
                >
                  Tap Die to Roll
                </p>
              )}

              <div className="flex items-center gap-2 shrink-0 mb-4">
                <div className="w-2 h-2 rounded-full bg-amber-600 shadow-[0_0_15px_var(--accent-red)]"></div>
                <div className="flex-1 flex items-center gap-2">
                  <select
                    value={activeCollectionId ?? 'all'}
                    onChange={handleCollectionChange}
                    className="min-w-0 w-full max-w-[240px] bg-white/5 border border-white/10 rounded-lg px-3 py-1.5 text-[10px] font-black uppercase tracking-wider text-stone-300 focus:outline-none focus:ring-2 focus:ring-amber-600/40"
                    aria-label="Roll pool collection"
                    disabled={isCollectionsLoading}
                  >
                    <option value="all">Roll Pool: All Collections</option>
                    {collections.map((collection) => (
                      <option key={collection.id} value={collection.id}>
                        Roll Pool: {collection.name}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    onClick={() => setIsCollectionDialogOpen(true)}
                    className="shrink-0 px-2 py-1.5 bg-white/5 border border-white/10 rounded-lg text-[10px] font-black uppercase tracking-wider text-stone-300 hover:bg-white/10 transition-colors"
                    aria-label="Add collection"
                  >
                    + New
                  </button>
                </div>
              </div>

              <div className="space-y-2" data-roll-pool>
                {pool.length === 0 ? (
                  <div className="text-center py-10 space-y-3">
                    <div className="text-3xl">📚</div>
                    <p className="text-xs text-stone-500 font-black uppercase tracking-widest">Queue Empty</p>
                    <p className="text-[10px] text-stone-600">Add comics to your queue to start rolling</p>
                    <button
                      onClick={() => navigate('/queue')}
                      className="mt-2 px-4 py-2 bg-amber-600/10 hover:bg-amber-600/20 border border-amber-600/20 rounded-lg text-[10px] font-bold uppercase tracking-widest text-amber-500 transition-colors"
                    >
                      Add Thread
                    </button>
                  </div>
                ) : (
                  pool.map((thread, index) => {
                    const isSelected = selectedThreadId && Number(selectedThreadId) === thread.id
                    return (
                      <div
                        key={thread.id}
                        onClick={() => handleThreadClick(thread)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' || e.key === ' ') {
                            e.preventDefault()
                            handleThreadClick(thread)
                          }
                        }}
                        role="button"
                        tabIndex={0}
                        className={`flex items-center gap-3 px-4 py-2 bg-white/5 border border-white/5 rounded-xl group transition-all cursor-pointer hover:bg-white/10 ${isSelected ? 'pool-thread-selected' : ''
                          }`}
                      >
                        <span className="text-lg font-black text-stone-500/50 group-hover:text-stone-400/50 transition-colors">
                          #{index + 1}
                        </span>
                        <div className="flex-1 min-w-0">
                          <p className="font-black text-stone-300 truncate text-sm">{thread.title}</p>
                          <p className="text-[8px] font-black text-stone-500 uppercase tracking-widest">{thread.format}</p>
                        </div>
                      </div>
                    )
                  })
                )}
              </div>

              {staleThread && !isRatingView && (
                <div
                  onClick={handleReadStale}
                  className="mt-8 animate-[fade-in_0.5s_ease-out] cursor-pointer hover:bg-amber-500/5 transition-colors rounded-xl"
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      handleReadStale()
                    }
                  }}
                >
                  <div className="px-4 py-3 bg-amber-500/5 border border-amber-500/10 rounded-xl flex items-center gap-3">
                    <div className="w-8 h-8 bg-amber-500/10 rounded-lg flex items-center justify-center shrink-0">
                      <span className="text-sm">⏳</span>
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-[10px] font-bold text-amber-200/70 uppercase tracking-wider leading-relaxed">
                        You haven't touched <span className="text-amber-400 font-black">{staleThread.title}</span> in{' '}
                        <span className="text-amber-400 font-black">{staleThread.days}</span> days
                      </p>
                      <p className="text-[9px] text-amber-300/70 text-center mt-1">
                        Tap to read now
                      </p>
                    </div>
                  </div>
                </div>
              )}

              {session.snoozed_threads?.length > 0 && !isRatingView && (
                <div className="mt-8">
                  <button
                    type="button"
                    onClick={() => setSnoozedExpanded(!snoozedExpanded)}
                    className="w-full px-4 py-2 bg-stone-500/5 border border-stone-500/10 rounded-xl flex items-center gap-2 hover:bg-stone-500/10 transition-colors"
                  >
                    <span
                      className={`text-stone-400 text-xs transition-transform ${snoozedExpanded ? 'rotate-90' : ''}`}
                    >
                      ▶
                    </span>
                    <span className="text-[10px] font-black text-stone-400 uppercase tracking-widest">
                      Snoozed ({session.snoozed_threads.length})
                    </span>
                  </button>
                  {snoozedExpanded && (
                    <div className="mt-2 space-y-1">
                      {session.snoozed_threads.map((thread) => (
                        <div
                          key={thread.id}
                          className="flex items-center gap-2 px-4 py-2 bg-white/5 border border-white/5 rounded-lg"
                        >
                          <p className="flex-1 text-sm text-stone-400 truncate">{thread.title}</p>
                          <button
                            type="button"
                            onClick={() => handleUnsnooze(thread.id)}
                            disabled={unsnoozeMutation.isPending}
                            className="px-2 py-1 text-xs text-rose-400 hover:text-rose-300 hover:bg-rose-500/10 rounded-lg transition-colors disabled:opacity-50"
                            title="Unsnooze this comic"
                            aria-label="Unsnooze this comic"
                          >
                            ✕
                          </button>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>

        <div id="explosion-layer" className="explosion-wrap"></div>

        {isCollectionDialogOpen && (
          <CollectionDialog onClose={() => setIsCollectionDialogOpen(false)} />
        )}

        {showMigrationDialog && threadToMigrate && (
          <MigrationDialog
            thread={threadToMigrate}
            onComplete={handleMigrationComplete}
            onSkip={handleMigrationSkip}
            onClose={handleMigrationClose}
          />
        )}

        {showSimpleMigration && activeRatingThread && (
            <SimpleMigrationDialog
              threadTitle={activeRatingThread.title}
              onComplete={handleSimpleMigrationComplete}
              onClose={() => setShowSimpleMigration(false)}
            />
        )}

        <Modal isOpen={isOverrideOpen} title="Override Roll" onClose={() => setIsOverrideOpen(false)}>
          <form className="space-y-4" onSubmit={handleOverrideSubmit}>
            <p className="text-xs text-stone-400">Pick a thread to force next roll result.</p>
            <div className="space-y-2">
              <label className="text-[10px] font-bold uppercase tracking-widest text-stone-500">Thread</label>
              <select
                value={overrideThreadId}
                onChange={(event) => setOverrideThreadId(event.target.value)}
                className="w-full bg-white/5 border border-white/10 rounded-xl px-3 py-2 text-sm text-stone-300"
                required
              >
                <option value="">Select a thread...</option>
                <optgroup label="Active Threads">
                  {activeThreads.map((thread) => (
                    <option key={thread.id} value={thread.id}>
                      {thread.title} ({thread.format})
                    </option>
                  ))}
                </optgroup>
                {session.snoozed_threads?.length > 0 && (
                  <optgroup label="Snoozed Threads">
                    {session.snoozed_threads.map((thread) => (
                      <option key={thread.id} value={thread.id}>
                        {thread.title} ({thread.format})
                      </option>
                    ))}
                  </optgroup>
                )}
              </select>
            </div>
            <button
              type="submit"
              disabled={overrideMutation.isPending || !overrideThreadId}
              className="w-full py-3 glass-button text-xs font-black uppercase tracking-widest disabled:opacity-60"
            >
              {overrideMutation.isPending ? 'Overriding...' : 'Override Roll'}
            </button>
          </form>
        </Modal>

        <Modal isOpen={isDieModalOpen} title="Select Die" onClose={() => setIsDieModalOpen(false)}>
          <div className="grid grid-cols-3 gap-2">
            {DICE_LADDER.map((die) => (
              <button
                key={die}
                onClick={async () => {
                  try {
                    await handleSetDie(die)
                    setIsDieModalOpen(false)
                  } catch (error) {
                    console.error('Failed to set die:', error)
                  }
                }}
                disabled={setDieMutation.isPending}
                className={`px-3 py-3 text-sm font-black rounded-lg border transition-colors ${die === currentDie
                  ? 'bg-amber-600/20 border-amber-600 text-amber-500'
                  : 'bg-white/5 border-white/10 hover:bg-white/10'
                  }`}
              >
                d{die}
              </button>
            ))}
            <button
              onClick={async () => {
                try {
                  await handleClearManualDie()
                  setIsDieModalOpen(false)
                } catch (error) {
                  console.error('Failed to clear manual die:', error)
                }
              }}
              disabled={clearManualDieMutation.isPending}
              className={`px-3 py-3 text-sm font-black rounded-lg border transition-colors ${session.manual_die
                ? 'bg-amber-500/20 border-amber-500 text-amber-400'
                : 'bg-white/5 border-white/10 hover:bg-white/10'
                }`}
            >
              Auto
            </button>
          </div>
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
              onClick={() => handleAction('edit')}
              className="w-full py-3 px-4 bg-white/5 border border-white/10 rounded-xl text-left text-sm font-black text-stone-300 hover:bg-white/10 transition-all flex items-center gap-3"
            >
              <span className="text-lg">✏️</span>
              <span>Edit Thread</span>
            </button>
          </div>
        </Modal>
      </div>
    </div>
  )
}
