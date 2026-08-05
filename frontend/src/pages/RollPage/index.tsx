import { useEffect, useMemo, useCallback, useState } from 'react'
import type { ChangeEvent, FormEvent, KeyboardEvent } from 'react'
import LazyDice3D from '../../components/LazyDice3D'
import Modal from '../../components/Modal'
import Tooltip from '../../components/Tooltip'
import MigrationDialog from '../../components/MigrationDialog'
import SimpleMigrationDialog from '../../components/SimpleMigrationDialog'
import { useNavigate } from 'react-router-dom'
import { DICE_LADDER } from '../../components/diceLadder'
import { useRollBootstrap } from '../../hooks/useRollBootstrap'
import { useBugReportRestore } from '../../contexts/useBugReportRestore'
import {
  useClearManualDie,
  useDismissPending,
  useOverrideRoll,
  useRoll,
  useSetDie,
} from '../../hooks/useRoll'
import { useSnooze, useUnsnooze } from '../../hooks/useSnooze'
import { useMoveToBack, useMoveToFront, useShuffleQueue } from '../../hooks/useQueue'
import { useRate } from '../../hooks'
import { threadsApi, dependenciesApi } from '../../services/api'
import { readingOrdersApi } from '../../services/api-reading-orders'
import { getApiErrorStatus, getApiErrorDetail } from '../../utils/apiError'
import { isDiceSide } from '../../components/diceTypes'
import type { Thread, ConnectedThreadInfo } from '../../types'
import type { RollBootstrapThread } from '../../types/rollBootstrap'
import { useRollPageState } from './useRollPageState'
import type { RatingThread, ThreadMetadata } from './types'
import {
  RATING_THRESHOLD,
  createExplosion,
  buildRatingThread,
} from './utils'
import { RatingView } from './components/RatingView'
import { ThreadPool } from './components/ThreadPool'

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

  const [readingOrders, setReadingOrders] = useState<import('../../services/api-reading-orders').ReadingOrder[]>([])
  const [connectedThreads, setConnectedThreads] = useState<ConnectedThreadInfo[]>([])

  const { data: bootstrap, refetch: refetchBootstrap, isPending: isBootstrapLoading, isError: isBootstrapError, error: bootstrapError } = useRollBootstrap()
  const { setRestoreAction, clearRestoreAction } = useBugReportRestore()
  const navigate = useNavigate()

  const snoozedThreads = useMemo(() => bootstrap?.snoozed_threads ?? [], [bootstrap?.snoozed_threads])

  useEffect(() => {
    if (isBootstrapError && bootstrapError) {
      const status = getApiErrorStatus(bootstrapError)
      if (status === 401) navigate('/login')
    }
  }, [isBootstrapError, bootstrapError, navigate])

  const setDieMutation = useSetDie()
  const clearManualDieMutation = useClearManualDie()
  const rollMutation = useRoll()
  const dismissPendingMutation = useDismissPending()
  const overrideMutation = useOverrideRoll()
  const snoozeMutation = useSnooze()
  const unsnoozeMutation = useUnsnooze()
  const moveToFrontMutation = useMoveToFront()
  const moveToBackMutation = useMoveToBack()
  const shuffleQueueMutation = useShuffleQueue()
  const rateMutation = useRate()

  async function handleUnsnooze(threadId: number) {
    try {
      await unsnoozeMutation.mutate(threadId)
      await refetchBootstrap()
    } catch (error) {
      console.error('Unsnooze failed:', error)
    }
  }

  async function handleShufflePool() {
    try {
      await shuffleQueueMutation.mutate()
      await refetchBootstrap()
    } catch (error) {
      console.error('Shuffle failed:', error)
      alert(`Failed to shuffle pool: ${getApiErrorDetail(error)}`)
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

  function handleThreadClick(thread: RollBootstrapThread) {
    setSelectedThread(thread)
    setIsActionSheetOpen(true)
  }

  async function handleToggleBlocked() {
    if (!blockedExpanded) {
      const blockedThreads = bootstrap?.blocked_threads ?? []
      const details = await Promise.all(
        blockedThreads.map(async (thread): Promise<[number, string[]]> => {
          try {
            const info = await dependenciesApi.getBlockingInfo(thread.id)
            return [thread.id, info.blocking_reasons ?? []]
          } catch {
            return [thread.id, []]
          }
        }),
      )
      setBlockingReasonMap(Object.fromEntries(details))
    }
    setBlockedExpanded(!blockedExpanded)
  }

  const enterRatingView = useCallback(async (threadId: number | null, result: number | null = null, threadMetadata: ThreadMetadata | null = null) => {
    const ratingThread = buildRatingThread(threadId, result, threadMetadata, bootstrap?.active_thread)
    if (!ratingThread) {
      setErrorMessage('Unable to load the selected thread.')
      setIsRatingView(false)
      return
    }

    setIsActionSheetOpen(false)
    setIsOverrideOpen(false)
    setIsDieModalOpen(false)

    setSelectedThreadId(threadId)
    if (result !== null) setRolledResult(result)
    setActiveRatingThread(ratingThread)

    setRating(3.0)
    setErrorMessage('')
    const die = currentDie || 6
    const idx = DICE_LADDER.indexOf(die)
    setPredictedDie(idx > 0 ? DICE_LADDER[idx - 1] : DICE_LADDER[0])
    setIsRatingView(true)
    suppressPendingAutoOpenRef.current = false

    if (threadId) {
      try {
        const ordersResponse = await readingOrdersApi.getForThread(threadId)
        setReadingOrders(ordersResponse.reading_orders)
      } catch (error) {
        console.error('Failed to fetch reading orders:', error)
        setReadingOrders([])
      }
      try {
        const connectedResponse = await dependenciesApi.getConnectedThreads(threadId)
        setConnectedThreads(connectedResponse.connected_threads)
      } catch (error) {
        console.error('Failed to fetch connected threads:', error)
        setConnectedThreads([])
      }
    } else {
      setReadingOrders([])
      setConnectedThreads([])
    }
  }, [bootstrap, currentDie, suppressPendingAutoOpenRef, setSelectedThreadId, setRolledResult, setActiveRatingThread, setRating, setErrorMessage, setPredictedDie, setIsRatingView, setIsActionSheetOpen, setIsOverrideOpen, setIsDieModalOpen])

  const handleMigrationComplete = useCallback((migratedThread: Thread) => {
    refetchBootstrap()
    setShowMigrationDialog(false)
    setThreadToMigrate(null)
    enterRatingView(migratedThread.id, null, migratedThread)
  }, [refetchBootstrap, enterRatingView, setShowMigrationDialog, setThreadToMigrate])

  const handleMigrationSkip = useCallback(() => {
    setShowMigrationDialog(false)
    if (threadToMigrate) enterRatingView(threadToMigrate.id, null, threadToMigrate)
  }, [threadToMigrate, enterRatingView, setShowMigrationDialog])

  const handleMigrationClose = useCallback(() => {
    setShowMigrationDialog(false)
    setThreadToMigrate(null)
  }, [setShowMigrationDialog, setThreadToMigrate])

  const handleSimpleMigrationComplete = useCallback((issueNumber: string) => {
    // Rating a stale thread moves it out of the stale set, so refresh the stale
    // data (via bootstrap) only when the rated thread was already rendered as
    // stale. This preserves stale indicators without a bootstrap refetch on
    // every rating.
    const wasStale = bootstrap?.stale_thread?.id === activeRatingThread!.id
    setShowSimpleMigration(false)
    rateMutation.mutate({
      thread_id: activeRatingThread!.id,
      rating,
      finish_session: false,
      issue_number: issueNumber,
    }).then(async (rateResponse) => {
      if (rateResponse && activeRatingThread) {
        setActiveRatingThread({
          ...activeRatingThread,
          issues_remaining: rateResponse.issues_remaining,
          total_issues: rateResponse.total_issues ?? null,
          reading_progress: rateResponse.reading_progress ?? null,
          last_rolled_result: null,
        })
      }
      suppressPendingAutoOpenRef.current = true
      setIsRolling(false)
      setIsRatingView(false)
      setRolledResult(null)
      setSelectedThreadId(null)
      setActiveRatingThread(null)
      setErrorMessage('')
      if (wasStale) {
        await refetchBootstrap()
      }
    }).catch((error: unknown) => {
      setErrorMessage(getApiErrorDetail(error))
    })
  }, [activeRatingThread, rating, rateMutation, refetchBootstrap, bootstrap, setShowSimpleMigration, suppressPendingAutoOpenRef, setIsRolling, setIsRatingView, setRolledResult, setSelectedThreadId, setActiveRatingThread, setErrorMessage])

  async function handleAction(action: string) {
    setIsActionSheetOpen(false)
    const isSnoozed = bootstrap?.snoozed_threads?.some((t) => t.id === selectedThread!.id) ?? false

    try {
      switch (action) {
        case 'read': {
          const response = await threadsApi.setPending(selectedThread!.id)
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
          await moveToFrontMutation.mutate(selectedThread!.id)
          await refetchBootstrap()
          break
        case 'move-back':
          await moveToBackMutation.mutate(selectedThread!.id)
          await refetchBootstrap()
          break
        case 'snooze':
          if (isSnoozed) {
            await unsnoozeMutation.mutate(selectedThread!.id)
          } else {
            await snoozeMutation.mutate()
          }
          await refetchBootstrap()
          break
        case 'edit':
          navigate('/queue', { state: { editThreadId: selectedThread!.id } })
          break
      }
    } catch (error) {
      console.error('Action failed:', error)
    }
  }

  const rollPool = useMemo(() => bootstrap?.roll_pool ?? [], [bootstrap?.roll_pool])
  const blockedThreads = bootstrap?.blocked_threads ?? []
  const displayDie = isDiceSide(currentDie) ? currentDie : 6

  const [overrideThreads, setOverrideThreads] = useState<Thread[] | null>(null)
  useEffect(() => {
    if (!isOverrideOpen || overrideThreads) return

    let cancelled = false
    const snoozedIds = new Set(snoozedThreads.map((thread) => thread.id))

    async function loadAllOverrideThreads() {
      const collected: Thread[] = []
      let pageToken: string | null = null
      do {
        const result = await threadsApi.list(
          { page_size: 200 },
          pageToken ?? undefined,
        )
        collected.push(...result.threads)
        pageToken = result.next_page_token ?? null
      } while (pageToken)

      if (!cancelled) {
        setOverrideThreads(
          collected.filter(
            (thread) => thread.status === 'active' && !snoozedIds.has(thread.id),
          ),
        )
      }
    }

    loadAllOverrideThreads().catch(() => {
      if (!cancelled) setOverrideThreads([])
    })

    return () => {
      cancelled = true
    }
  }, [isOverrideOpen, overrideThreads, snoozedThreads])

  useEffect(() => {
    if (showSimpleMigration) {
      setRestoreAction(() => {
        setShowSimpleMigration(true)
      })
      return
    }
    if (showMigrationDialog && threadToMigrate) {
      setRestoreAction(() => {
        setShowMigrationDialog(true)
      })
      return
    }
    if (isOverrideOpen) {
      setRestoreAction(() => {
        setIsOverrideOpen(true)
      })
      return
    }
    if (isActionSheetOpen && selectedThread) {
      setRestoreAction(() => {
        setIsActionSheetOpen(true)
      })
      return
    }
    clearRestoreAction()
  }, [
    clearRestoreAction,
    isActionSheetOpen,
    isOverrideOpen,
    selectedThread,
    setIsActionSheetOpen,
    setIsOverrideOpen,
    setRestoreAction,
    setShowMigrationDialog,
    setShowSimpleMigration,
    showMigrationDialog,
    showSimpleMigration,
    threadToMigrate,
  ])

  useEffect(() => {
    if (bootstrap?.current_die) setCurrentDie(bootstrap.current_die)
    if (bootstrap?.last_rolled_result !== undefined && bootstrap?.last_rolled_result !== null) {
      setRolledResult(bootstrap.last_rolled_result)
    }
  }, [bootstrap?.current_die, bootstrap?.last_rolled_result, setCurrentDie, setRolledResult])

  useEffect(() => {
    if (suppressPendingAutoOpenRef.current) return
    const pendingThreadId = bootstrap?.pending_thread_id
    if (!pendingThreadId) return

    const pendingId = Number(pendingThreadId)
    const isCurrentPendingSelection = Number(selectedThreadId) === pendingId
    const hasHydratedPendingMetadata = Boolean(activeRatingThread?.title)

    if (isRatingView && isCurrentPendingSelection && hasHydratedPendingMetadata) return

    const pendingFromSession = bootstrap?.active_thread && bootstrap.active_thread.id === pendingId
      ? { id: bootstrap.active_thread.id, title: bootstrap.active_thread.title, format: bootstrap.active_thread.format,
          issues_remaining: bootstrap.active_thread.issues_remaining ?? 0, queue_position: bootstrap.active_thread.queue_position ?? 0,
          total_issues: bootstrap.active_thread.total_issues ?? null, reading_progress: bootstrap.active_thread.reading_progress ?? null,
          issue_id: bootstrap.active_thread.issue_id ?? null, issue_number: bootstrap.active_thread.issue_number ?? null,
          next_issue_id: bootstrap.active_thread.next_issue_id ?? null, next_issue_number: bootstrap.active_thread.next_issue_number ?? null,
          last_rolled_result: bootstrap.last_rolled_result ?? bootstrap.active_thread.last_rolled_result ?? null }
      : null

    const pendingFromPool = !pendingFromSession && rollPool.length > 0
      ? rollPool.find((thread) => thread.id === pendingId) : null

    const pendingResult = pendingFromSession?.last_rolled_result ?? bootstrap?.last_rolled_result ?? null
    const pendingMetadata = (pendingFromSession ?? pendingFromPool) as ThreadMetadata | null
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
    setIsActionSheetOpen(false)
    setIsOverrideOpen(false)
    setIsDieModalOpen(false)
  }, [bootstrap?.pending_thread_id, bootstrap?.active_thread, bootstrap?.last_rolled_result, rollPool, activeRatingThread, currentDie, isRatingView, selectedThreadId, suppressPendingAutoOpenRef, setSelectedThreadId, setRolledResult, setActiveRatingThread, setRating, setErrorMessage, setPredictedDie, setIsRatingView, setIsActionSheetOpen, setIsOverrideOpen, setIsDieModalOpen])

  useEffect(() => {
    const staleFromBootstrap = bootstrap?.stale_thread ?? null
    const count = bootstrap?.stale_thread_count ?? 0
    if (staleFromBootstrap && count > 0) {
      const lastActivity = staleFromBootstrap.last_activity_at ? new Date(staleFromBootstrap.last_activity_at) : new Date()
      const diffDays = Math.floor((Date.now() - lastActivity.getTime()) / (1000 * 60 * 60 * 24))
      setStaleThread({ ...staleFromBootstrap, days: Math.max(diffDays, 7) })
      setStaleThreadCount(count)
    } else {
      setStaleThread(null)
      setStaleThreadCount(0)
    }
  }, [bootstrap?.stale_thread, bootstrap?.stale_thread_count, setStaleThread, setStaleThreadCount])

  useEffect(() => {
    return () => {
      if (rollIntervalRef.current) clearInterval(rollIntervalRef.current)
      if (rollTimeoutRef.current) clearTimeout(rollTimeoutRef.current)
    }
  }, [rollIntervalRef, rollTimeoutRef])

  function updateRatingUI(val: string) {
    const num = parseFloat(val)
    if (num === RATING_THRESHOLD) navigator.vibrate?.(8)
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
    navigator.vibrate?.(20)
    if (rating >= RATING_THRESHOLD) createExplosion()

    const freshTotalIssues =
      bootstrap?.active_thread?.id === activeRatingThread?.id
        ? bootstrap?.active_thread?.total_issues ?? activeRatingThread?.total_issues
        : activeRatingThread?.total_issues

    if (activeRatingThread && freshTotalIssues === null) {
      setShowSimpleMigration(true)
      return
    }

    if (!activeRatingThread) return

    // Capture stale-set membership before the mutation: a rated thread leaves the
    // stale set, so refresh stale data (via bootstrap) only when it was rendered
    // as stale. This avoids a bootstrap round trip on every rating.
    const wasStale = bootstrap?.stale_thread?.id === activeRatingThread.id

    try {
      const rateResponse = await rateMutation.mutate({
        thread_id: activeRatingThread.id,
        rating,
        finish_session: finishSession,
        issue_number: activeRatingThread.issue_number || undefined,
      })

      if (rateResponse) {
        setActiveRatingThread({
          ...activeRatingThread,
          issues_remaining: rateResponse.issues_remaining,
          queue_position: rateResponse.queue_position,
          total_issues: rateResponse.total_issues ?? null,
          reading_progress: rateResponse.reading_progress ?? null,
          issue_id: rateResponse.next_unread_issue_id ?? null,
          issue_number: rateResponse.next_unread_issue_number ?? null,
          last_rolled_result: null,
        })
      }

      if (wasStale) {
        try {
          await refetchBootstrap()
        } catch {
          setErrorMessage('Rating saved but failed to refresh. Please refresh the page.')
          return
        }
      }

      setIsRolling(false)
      setIsRatingView(false)
      setRolledResult(null)
      setSelectedThreadId(null)
      setActiveRatingThread(null)
      setErrorMessage('')
    } catch (error: unknown) {
      setErrorMessage(getApiErrorDetail(error))
    }
  }

  async function handleSnooze() {
    try {
      await snoozeMutation.mutate()
      await refetchBootstrap()
      setIsRolling(false)
      setIsRatingView(false)
      setRolledResult(null)
      setSelectedThreadId(null)
      setActiveRatingThread(null)
    } catch (error: unknown) {
      setErrorMessage(getApiErrorDetail(error))
    }
  }

  async function handleRefreshThread() {
    try {
      const latest = await refetchBootstrap()
      const refreshedThread = latest?.active_thread

      if (activeRatingThread && refreshedThread?.id === activeRatingThread.id) {
        setActiveRatingThread({
          ...activeRatingThread,
          issues_remaining: refreshedThread.issues_remaining ?? 0,
          queue_position: refreshedThread.queue_position ?? activeRatingThread.queue_position,
          total_issues: refreshedThread.total_issues ?? null,
          reading_progress: refreshedThread.reading_progress ?? null,
          issue_id: refreshedThread.issue_id ?? null,
          issue_number: refreshedThread.issue_number ?? null,
          next_issue_id: refreshedThread.next_issue_id ?? null,
          next_issue_number: refreshedThread.next_issue_number ?? null,
          last_rolled_result: refreshedThread.last_rolled_result ?? activeRatingThread.last_rolled_result,
        })
      }
    } catch (error: unknown) {
      setErrorMessage(getApiErrorDetail(error))
    }
  }

  const dieSize = currentDie || 6
  const filteredThreads = rollPool.filter((thread) => !isRatingView || thread.id !== (selectedThreadId ? Number(selectedThreadId) : null))
  const pool = filteredThreads.slice(0, dieSize)
  const hasValidRolledResult = Number.isInteger(rolledResult) && rolledResult !== null && rolledResult >= 1 && rolledResult <= currentDie

  async function handleSetDie(die: number) {
    try {
      await setDieMutation.mutate(die)
      setCurrentDie(die)
      return true
    } catch (error: unknown) {
      setErrorMessage(getApiErrorDetail(error))
      return false
    }
  }

  async function handleClearManualDie() {
    try {
      await clearManualDieMutation.mutate()
    } catch (error: unknown) {
      setErrorMessage(getApiErrorDetail(error))
    }
  }

  async function recoverPendingRollConflict() {
    const latest = await refetchBootstrap()
    const pendingId = Number(latest?.pending_thread_id ?? bootstrap?.pending_thread_id ?? 0)
    if (!pendingId) return false
    const pendingMetadata = latest?.active_thread && latest.active_thread.id === pendingId
      ? latest.active_thread : latest?.roll_pool?.find((thread) => thread.id === pendingId)
    enterRatingView(pendingId, latest?.last_rolled_result ?? bootstrap?.last_rolled_result ?? null, pendingMetadata)
    return true
  }

  function handleRoll() {
    if (isRolling) return
    navigator.vibrate?.(15)
    if (bootstrap?.pending_thread_id && !suppressPendingAutoOpenRef.current) {
      const pendingId = Number(bootstrap.pending_thread_id)
      const pendingMetadata = bootstrap?.active_thread && bootstrap.active_thread.id === pendingId
        ? bootstrap.active_thread : rollPool.find((thread) => thread.id === pendingId)
      enterRatingView(pendingId, bootstrap?.last_rolled_result ?? null, pendingMetadata)
      return
    }

    if (suppressPendingAutoOpenRef.current && bootstrap?.pending_thread_id) {
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
      setOverrideErrorMessage(getApiErrorDetail(error))
    })
  }

  if (isBootstrapLoading && !bootstrap && !isBootstrapError) {
    return <div className="text-center py-10 text-stone-500 font-black uppercase tracking-widest text-[10px]">Loading...</div>
  }

  if (isBootstrapError || !bootstrap) {
    const errorDetail = getApiErrorDetail(bootstrapError)
    const status = getApiErrorStatus(bootstrapError)
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
            <button onClick={() => refetchBootstrap()} className="px-4 py-2 bg-amber-600/20 border border-amber-600/50 rounded-lg text-xs font-black uppercase tracking-widest text-amber-500 hover:bg-amber-600/30 transition-colors">
              Retry
            </button>
          )}
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen flex flex-col">
      <header className="flex justify-between items-center px-2 md:px-3 py-2 shrink-0 z-10">
        <div className="min-w-0">
          <h1 className="text-xl md:text-2xl font-black tracking-tighter text-glow uppercase">Pile Roller</h1>
          {snoozedThreads.length > 0 && currentDie >= DICE_LADDER[DICE_LADDER.length - 1] && (
            <div className="flex items-center gap-2 mt-1">
              <span className="text-[9px] text-stone-500 uppercase tracking-wider">pool at max size (d{dieSize}) - snoozing won't increase it further</span>
            </div>
          )}
          {snoozedThreads.length > 0 && pool.length + snoozedThreads.length > dieSize && (
            <div className="flex items-center gap-2 mt-1">
              <Tooltip content="Snoozed offset"><span className="modifier-badge text-[10px] font-black text-amber-500 cursor-help border-b border-dashed border-stone-600">+{snoozedThreads.length}</span></Tooltip>
              <Tooltip content="Snoozed offset active"><span className="text-[9px] text-stone-500 uppercase tracking-wider cursor-help border-b border-dashed border-stone-600">offset active</span></Tooltip>
            </div>
          )}
        </div>
        <div className="flex items-center gap-1 md:gap-2 shrink-0">
          <div id="die-selector">
            <div className="hidden md:flex gap-2">
              {DICE_LADDER.map((die) => (
                <button key={die} onClick={() => handleSetDie(die)} disabled={setDieMutation.isPending}
                  className={`die-btn px-2 py-1 text-[10px] font-black rounded-lg border transition-colors ${die === currentDie ? 'bg-amber-600/20 border-amber-600 text-amber-500' : 'bg-white/5 border-white/10 hover:bg-white/10'}`}>
                  d{die}
                </button>
              ))}
              <button onClick={handleClearManualDie} disabled={clearManualDieMutation.isPending}
                className={`px-2 py-1 text-[10px] font-black rounded-lg border transition-colors ${bootstrap.manual_die ? 'bg-amber-500/20 border-amber-500 text-amber-400' : 'bg-white/5 border-white/10 hover:bg-white/10'}`}
                title={bootstrap.manual_die ? `Exit manual mode (currently d${bootstrap.manual_die})` : 'Return to automatic dice ladder mode'}>
                Auto
              </button>
            </div>
            <div className="md:hidden">
              <button onClick={() => setIsDieModalOpen(true)} disabled={setDieMutation.isPending}
                className="px-3 py-1.5 text-[11px] font-black rounded-lg border bg-amber-600/20 border-amber-600 text-amber-500 transition-colors">
                d{currentDie}
              </button>
            </div>
          </div>
          <div className="hidden md:flex items-center gap-2 px-3 py-1 bg-white/5 rounded-xl border border-white/10 shrink-0">
            <div className="relative flex items-center justify-center" style={{ width: '40px', height: '40px' }}>
              <div className="w-full h-full">
                <LazyDice3D sides={displayDie} value={1} isRolling={false} showValue={false} color={0xffffff} />
              </div>
            </div>
            <div className="text-right">
              <Tooltip content="Dice ladder: d4→d6→d8→d10→d12→d20→d30→d50→d100. Promotes automatically based on ratings (5→up, 1-2→down)">
                <span className="block text-[8px] font-black text-stone-500 uppercase tracking-wider cursor-help border-b border-dashed border-stone-600">Ladder</span>
              </Tooltip>
              <span id="header-die-label" className="text-[10px] font-black text-amber-500">d{currentDie}</span>
            </div>
          </div>
          <Tooltip content="Manually select a thread to override the next roll result.">
            <button type="button" onClick={() => { setOverrideThreads(null); setIsOverrideOpen(true) }} className="px-2 md:px-3 py-1.5 md:py-2 bg-white/5 border border-white/10 text-stone-300 rounded-xl text-[10px] font-black uppercase tracking-widest hover:bg-white/10 transition-all">
              Override
            </button>
          </Tooltip>
        </div>
      </header>

      <div className="flex-1 flex flex-col min-h-0">
        <div className="flex-1 flex flex-col relative md:glass-card md:rounded-xl">
          <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-72 h-72 md:w-80 md:h-80 bg-amber-900/15 rounded-full blur-[100px] md:blur-[120px] pointer-events-none"></div>
          <div className="flex-1 flex flex-col">
            {!isRatingView ? (
              <div id="main-die-3d" onClick={handleRoll} onKeyDown={handleKeyDown} role="button" tabIndex={0} aria-label="Roll the dice"
                className={`dice-state-${diceState} relative z-10 cursor-pointer shrink-0 flex items-center justify-center rounded-full transition-all mt-4 md:mt-8 mx-auto active:scale-95`}
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
                readingOrders={readingOrders}
                connectedThreads={connectedThreads}
                onUpdateRating={updateRatingUI}
                onSubmitRating={handleSubmitRating}
                onSnooze={handleSnooze}
                onRefreshThread={handleRefreshThread}
                onCancel={async () => {
                  try {
                    await dismissPendingMutation.mutate()
                    await refetchBootstrap()
                  } catch (error) {
                    setErrorMessage(getApiErrorDetail(error))
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
              snoozedThreads={snoozedThreads}
              snoozedExpanded={snoozedExpanded}
              blockedExpanded={blockedExpanded}
              onThreadClick={handleThreadClick}
              onUnsnooze={handleUnsnooze}
              onReadStale={handleReadStale}
              onToggleSnoozed={() => setSnoozedExpanded(!snoozedExpanded)}
              onToggleBlocked={handleToggleBlocked}
              onShuffle={handleShufflePool}
              unsnoozeIsPending={unsnoozeMutation.isPending}
              shuffleIsPending={shuffleQueueMutation.isPending}
            />
          </div>
        </div>

        <div id="explosion-layer" className="explosion-wrap"></div>

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
              <select value={overrideThreadId} onChange={(event: ChangeEvent<HTMLSelectElement>) => setOverrideThreadId(event.target.value)}
                className="w-full bg-white/5 border border-solid border-white/20 rounded-xl px-3 py-2 text-sm text-stone-300 focus:outline-none focus:ring-2 focus:ring-amber-500/30 focus:border-amber-400 transition-colors" required>
                <option value="">Select a thread...</option>
                <optgroup label="Active Threads">
                  {(overrideThreads ?? []).map((thread) => (<option key={thread.id} value={thread.id}>{thread.title} ({thread.format})</option>))}
                </optgroup>
                {snoozedThreads.length > 0 && (
                  <optgroup label="Snoozed Threads">
                    {snoozedThreads.map((thread) => (<option key={thread.id} value={thread.id}>{thread.title} ({thread.format})</option>))}
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
              <button key={die} onClick={async () => { if (await handleSetDie(die)) setIsDieModalOpen(false) }}
                disabled={setDieMutation.isPending}
                className={`px-3 py-3 text-sm font-black rounded-lg border transition-colors ${die === currentDie ? 'bg-amber-600/20 border-amber-600 text-amber-500' : 'bg-white/5 border-white/10 hover:bg-white/10'}`}>
                d{die}
              </button>
            ))}
            <button onClick={async () => { await handleClearManualDie(); setIsDieModalOpen(false) }}
              disabled={clearManualDieMutation.isPending}
              className={`px-3 py-3 text-sm font-black rounded-lg border transition-colors ${bootstrap.manual_die ? 'bg-amber-500/20 border-amber-500 text-amber-400' : 'bg-white/5 border-white/10 hover:bg-white/10'}`}>
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
              <span className="text-lg">{snoozedThreads.some((thread) => thread.id === selectedThread?.id) ? '🔔' : '😴'}</span>
              <span>{snoozedThreads.some((thread) => thread.id === selectedThread?.id) ? 'Unsnooze' : 'Snooze'}</span>
            </button>
            <button type="button" onClick={() => handleAction('edit')} className="w-full py-3 px-4 bg-white/5 border border-white/10 rounded-xl text-left text-sm font-black text-stone-300 hover:bg-white/10 transition-all flex items-center gap-3">
              <span className="text-lg">✏️</span><span>Edit Thread</span>
            </button>
          </div>
        </Modal>
      </div>
    </div>
  )
}
