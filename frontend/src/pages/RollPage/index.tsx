import { useCallback, useEffect, useMemo, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import LazyDice3D from '../../components/LazyDice3D'
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
import { getApiErrorDetail, getApiErrorStatus } from '../../utils/apiError'
import { isDiceSide } from '../../components/diceTypes'
import { threadsApi } from '../../services/api'
import type { ThreadMetadata } from './types'
import { useRollPageState } from './useRollPageState'
import { useRollBootstrapSync } from './useRollBootstrapSync'
import { useRollPendingSession } from './useRollPendingSession'
import { useRollRating } from './useRollRating'
import { useRollSnooze } from './useRollSnooze'
import { useRollDependencies } from './useRollDependencies'
import { useRollActions } from './useRollActions'
import { useRollModals } from './useRollModals'
import { RatingView } from './components/RatingView'
import { ThreadPool } from './components/ThreadPool'
import { RollHeader } from './components/RollHeader'
import { RollModals } from './components/RollModals'

/**
 * Route entry for the Roll page. The component composes the focused retained
 * feature modules (`useRollBootstrapSync`, `useRollPendingSession`,
 * `useRollRating`, `useRollSnooze`, `useRollDependencies`, `useRollActions`,
 * `useRollModals`) plus the page-level navigation and error boundary concerns.
 * Data and mutation ownership stays in the page so a second cache layer is
 * never introduced.
 */
export default function RollPage() {
  const state = useRollPageState()
  const navigate = useNavigate()
  const mainDieRef = useRef<HTMLDivElement>(null)

  const {
    data: bootstrap,
    refetch: refetchBootstrap,
    isPending: isBootstrapLoading,
    isError: isBootstrapError,
    error: bootstrapError,
  } = useRollBootstrap()

  const scrollToDice = useCallback(() => {
    mainDieRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [])

  const prevIsRatingViewRef = useRef(state.isRatingView)
  useEffect(() => {
    const wasRatingView = prevIsRatingViewRef.current
    const isRatingView = state.isRatingView
    prevIsRatingViewRef.current = isRatingView
    if (wasRatingView && !isRatingView) {
      scrollToDice()
    }
  }, [state.isRatingView, scrollToDice])

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
  const { setRestoreAction, clearRestoreAction } = useBugReportRestore()

  useRollBootstrapSync({
    state,
    bootstrap,
    isBootstrapError,
    bootstrapError,
    navigate,
  })

  const rollPool = useMemo(() => bootstrap?.roll_pool ?? [], [bootstrap?.roll_pool])

  useRollPendingSession({ state, bootstrap, rollPool })

  const rating = useRollRating({
    state,
    bootstrap,
    rateMutation,
    dismissPendingMutation,
    refetchBootstrap,
  })

  const snooze = useRollSnooze({
    state,
    snoozeMutation,
    unsnoozeMutation,
    refetchBootstrap,
  })

  const dependencies = useRollDependencies({ state, bootstrap })

  const actions = useRollActions({
    state,
    bootstrap,
    rollPool,
    navigate,
    mutations: {
      setDieMutation,
      clearManualDieMutation,
      rollMutation,
      snoozeMutation,
      unsnoozeMutation,
      moveToFrontMutation,
      moveToBackMutation,
      shuffleQueueMutation,
    },
    refetchBootstrap,
    enterRatingView: rating.enterRatingView,
    threadsApi,
  })

  const modals = useRollModals({
    state,
    bootstrap,
    overrideMutation,
    enterRatingView: rating.enterRatingView,
    setRestoreAction,
    clearRestoreAction,
  })

  const handleSetCurrentIssue = async (issueNumber: string) => {
    if (!state.selectedThread) return
    try {
      const response = await threadsApi.setCurrentIssue(state.selectedThread.id, issueNumber)
      await refetchBootstrap()
      const threadMetadata: ThreadMetadata = {
        id: response.thread_id,
        title: response.title,
        format: response.format,
        issues_remaining: response.issues_remaining,
        queue_position: response.queue_position,
        total_issues: response.total_issues,
        reading_progress: response.reading_progress ?? null,
        issue_id: response.issue_id,
        issue_number: response.issue_number,
        next_issue_id: response.next_issue_id,
        next_issue_number: response.next_issue_number,
        last_rolled_result: null,
      }
      suppressPendingAutoOpenRef.current = true
      rating.enterRatingView(response.thread_id, null, threadMetadata)
    } catch (error) {
      console.error('Set current issue failed:', error)
      throw error
    }
  }

  const snoozedThreads = bootstrap?.snoozed_threads ?? []
  const blockedThreads = bootstrap?.blocked_threads ?? []
  const dieSize = state.currentDie || 6
  const filteredThreads = rollPool.filter(
    (thread) =>
      !state.isRatingView || thread.id !== (state.selectedThreadId ? Number(state.selectedThreadId) : null),
  )
  const pool = filteredThreads.slice(0, dieSize)
  const displayDie = isDiceSide(state.currentDie) ? state.currentDie : 6
  const hasValidRolledResult =
    Number.isInteger(state.rolledResult)
    && state.rolledResult !== null
    && state.rolledResult >= 1
    && state.rolledResult <= state.currentDie

  if (isBootstrapLoading && !bootstrap && !isBootstrapError) {
    return (
      <div className="text-center py-10 text-stone-500 font-black uppercase tracking-widest text-[10px]">
        Loading...
      </div>
    )
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
            <button
              onClick={() => navigate('/login')}
              className="px-4 py-2 bg-amber-600/20 border border-amber-600/50 rounded-lg text-xs font-black uppercase tracking-widest text-amber-500 hover:bg-amber-600/30 transition-colors"
            >
              Go to Login
            </button>
          ) : (
            <button
              onClick={() => refetchBootstrap()}
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
      <RollHeader
        bootstrap={bootstrap}
        currentDie={state.currentDie}
        dieSize={dieSize}
        displayDie={displayDie}
        snoozedThreads={snoozedThreads}
        pool={pool}
        isRatingView={state.isRatingView}
        setDiePending={setDieMutation.isPending}
        clearManualDiePending={clearManualDieMutation.isPending}
        onSetDie={actions.handleSetDie}
        onClearManualDie={actions.handleClearManualDie}
        onOpenOverride={modals.openOverrideModal}
        onOpenDieModal={() => state.setIsDieModalOpen(true)}
      />

      <div className="flex-1 flex flex-col min-h-0">
        <div className="flex-1 flex flex-col relative md:glass-card md:rounded-xl">
          <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-72 h-72 md:w-80 md:h-80 bg-amber-900/15 rounded-full blur-[100px] md:blur-[120px] pointer-events-none"></div>
          <div className="flex-1 flex flex-col">
            {!state.isRatingView ? (
              <div
                id="main-die-3d"
                ref={mainDieRef}
                onClick={actions.handleRoll}
                onKeyDown={actions.handleKeyDown}
                role="button"
                tabIndex={0}
                aria-label="Roll the dice"
                className={`dice-state-${state.diceState} relative z-10 cursor-pointer shrink-0 flex items-center justify-center rounded-full transition-all mt-4 md:mt-8 mx-auto active:scale-95`}
                style={{ width: '200px', height: '200px' }}
                data-testid="main-die-3d"
              >
                <div className="w-full h-full main-die-optical-center">
                  <LazyDice3D
                    sides={displayDie}
                    value={state.rolledResult || 1}
                    isRolling={state.isRolling}
                    showValue={false}
                    color={0xffffff}
                    onRollComplete={() => state.setDiceState('rolled')}
                  />
                </div>
              </div>
            ) : (
              <RatingView
                activeRatingThread={state.activeRatingThread}
                currentDie={state.currentDie}
                rolledResult={state.rolledResult}
                rating={state.rating}
                predictedDie={state.predictedDie}
                hasValidRolledResult={hasValidRolledResult}
                poolSize={pool.length}
                errorMessage={state.errorMessage}
                rateIsPending={rateMutation.isPending}
                snoozeIsPending={snoozeMutation.isPending}
                dismissIsPending={dismissPendingMutation.isPending}
                readingOrders={rating.readingOrders}
                connectedThreads={rating.connectedThreads}
                onUpdateRating={rating.updateRatingUI}
                onSubmitRating={rating.handleSubmitRating}
                onSnooze={snooze.handleSnooze}
                onRefreshThread={rating.handleRefreshThread}
                onCancel={rating.handleCancelRating}
              />
            )}

            <ThreadPool
              pool={pool}
              blockedThreads={blockedThreads}
              blockingReasonMap={state.blockingReasonMap}
              dieSize={dieSize}
              isRatingView={state.isRatingView}
              isRolling={state.isRolling}
              rolledResult={state.rolledResult}
              selectedThreadId={state.selectedThreadId}
              staleThread={state.staleThread}
              staleThreadCount={state.staleThreadCount}
              snoozedThreads={snoozedThreads}
              snoozedExpanded={state.snoozedExpanded}
              blockedExpanded={state.blockedExpanded}
              onThreadClick={actions.handleThreadClick}
              onUnsnooze={snooze.handleUnsnooze}
              onReadStale={actions.handleReadStale}
              onToggleSnoozed={() => state.setSnoozedExpanded(!state.snoozedExpanded)}
              onToggleBlocked={dependencies.handleToggleBlocked}
              onShuffle={actions.handleShufflePool}
              unsnoozeIsPending={unsnoozeMutation.isPending}
              shuffleIsPending={shuffleQueueMutation.isPending}
            />
          </div>
        </div>

        <div id="explosion-layer" className="explosion-wrap"></div>

        <RollModals
          showMigrationDialog={state.showMigrationDialog}
          threadToMigrate={state.threadToMigrate}
          onMigrationComplete={rating.handleMigrationComplete}
          onMigrationSkip={rating.handleMigrationSkip}
          onMigrationClose={rating.handleMigrationClose}
          showSimpleMigration={state.showSimpleMigration}
          activeRatingThread={state.activeRatingThread}
          onSimpleMigrationComplete={rating.handleSimpleMigrationComplete}
          onCloseSimpleMigration={() => state.setShowSimpleMigration(false)}
          isOverrideOpen={state.isOverrideOpen}
          overrideThreads={modals.overrideThreads}
          overrideThreadId={state.overrideThreadId}
          onOverrideThreadIdChange={state.setOverrideThreadId}
          overrideErrorMessage={state.overrideErrorMessage}
          onSubmitOverride={modals.handleOverrideSubmit}
          overridePending={overrideMutation.isPending}
          snoozedThreads={snoozedThreads}
          onCloseOverride={modals.closeOverrideModal}
          isDieModalOpen={state.isDieModalOpen}
          onCloseDieModal={() => state.setIsDieModalOpen(false)}
          manualDie={bootstrap.manual_die}
          currentDie={state.currentDie}
          onSetDie={actions.handleSetDie}
          onClearManualDie={actions.handleClearManualDie}
          setDiePending={setDieMutation.isPending}
          clearManualDiePending={clearManualDieMutation.isPending}
          isActionSheetOpen={state.isActionSheetOpen}
          selectedThread={state.selectedThread}
          onCloseActionSheet={() => state.setIsActionSheetOpen(false)}
          onAction={actions.handleAction}
          isSetCurrentIssueOpen={state.isSetCurrentIssueOpen}
          onCloseSetCurrentIssue={() => state.setIsSetCurrentIssueOpen(false)}
          onSetCurrentIssue={handleSetCurrentIssue}
        />
      </div>
    </div>
  )
}