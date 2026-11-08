import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import LazyDice3D from '../../components/LazyDice3D'
import { useRollBootstrap } from '../../hooks/useRollBootstrap'
import {
  useRollDieState,
  useRollEligibleIssueIds,
  useRollIssueCards,
} from '../../hooks/useRollResources'
import { useBugReportRestore } from '../../contexts/useBugReportRestore'
import {
  useResetDice,
  useDismissPending,
  useOverrideRoll,
  useRoll,
  useSetDie,
} from '../../hooks/useRoll'
import { useSnooze } from '../../hooks/useSnooze'
import { useMoveToBack, useMoveToFront, useShuffleQueue, useActiveSeriesCount } from '../../hooks/useQueue'
import { useTasteDiscoveries } from '../../hooks/useTasteDiscoveries'
import { useRate } from '../../hooks'
import { getApiErrorDetail, getApiErrorStatus } from '../../utils/apiError'
import { isDiceSide } from '../../components/diceTypes'
import { threadsApi } from '../../services/api-threads'
import { readRollSnoozes } from '../../services/api-roll'
import type { RollBootstrapThread } from '../../types/rollBootstrap'
import type { ThreadMetadata } from './types'
import { useRollPageState } from './useRollPageState'
import { useRollBootstrapSync } from './useRollBootstrapSync'
import { useRollPendingSession } from './useRollPendingSession'
import { useRollRating } from './useRollRating'
import { useRollSnooze } from './useRollSnooze'
import { useRollActions } from './useRollActions'
import { useRollModals } from './useRollModals'
import { useRollViewport } from './useRollViewport'
import { useRatingView } from './useRatingView'
import { RatingView } from './components/RatingView'
import { PostRateCopyPrompt } from './components/PostRateCopyPrompt'
import { LastReadStrip } from './components/LastReadStrip'
import { useRollLastRead } from '../../hooks/useRollLastRead'
import { useSnapshots, useUndo } from '../../hooks/useUndo'
import { useToast } from '../../contexts/useToast'
import { invalidateAfterUndo, invalidateRollBootstrapOnNavigation } from '../../query/cacheEffects'
import { ThreadPool } from './components/ThreadPool'
import { RollHeader } from './components/RollHeader'
import { RollFooter } from './components/RollFooter'
import { RollModals } from './components/RollModals'
import { RollCta } from './components/RollCta'
import { TasteDiscoveryCard } from './components/TasteDiscoveryCard'
import ReadingModeLauncher from '../../components/ReadingModeLauncher'
import { ReadingGraphProblemCard } from '../../components/ReadingGraphProblemCard'

/**
 * Route entry for the Roll page. The component composes the focused retained
 * feature modules (`useRollBootstrapSync`, `useRollPendingSession`,
 * `useRollRating`, `useRollSnooze`, `useRollActions`,
 * `useRollModals`, `useRollViewport`) plus the page-level navigation and
 * error boundary concerns.
 * Data and mutation ownership stays in the page so a second cache layer is
 * never introduced.
 */
export default function RollPage() {
  const state = useRollPageState()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const {
    data: bootstrap,
    refetch: refetchBootstrap,
    isPending: isBootstrapLoading,
    isError: isBootstrapError,
    error: bootstrapError,
    isRetrying: isBootstrapRetrying,
  } = useRollBootstrap()

  // Die-header surface migration (#4719): the scoped die resource is
  // authoritative for the selected die, ladder readout, die size and 3D
  // model. Bootstrap remains the fallback while the query settles or fails.
  const { data: cachedScopedDieState, isError: isScopedDieStateError } = useRollDieState()
  // TanStack Query preserves previously successful data after a failed refetch.
  // A failed scoped refresh must not overrule the newly reconciled bootstrap die.
  const scopedDieState = isScopedDieStateError ? undefined : cachedScopedDieState

  // Eligible-pool surface migration (#4719): the scoped resource owns the
  // ordered thread ids for the current die, with the browser snooze cookie
  // passed exactly as Roll's offer sends it. Bootstrap remains the source of
  // each face's display metadata and the fallback while this query settles.
  const browserSnoozedThreadIds = readRollSnoozes()
  const { data: scopedEligibleIssueIds } = useRollEligibleIssueIds(browserSnoozedThreadIds)

  // Issue-card surface migration (#4719): enrich the visible eligible batch
  // from one bounded scoped read. Cards are authoritative for the fields they
  // carry; bootstrap remains the fallback while this query settles or fails.
  const { data: scopedIssueCards } = useRollIssueCards(
    scopedEligibleIssueIds?.issue_ids ?? [],
  )

  // The committed rate response seeds this cache, so the idle strip renders
  // the saved rating and updated stats without a second GET (#2720).
  const lastRead = useRollLastRead(bootstrap?.last_read ?? null)
  const lastReadKey = lastRead
    ? `${lastRead.lastRead.issue_id ?? 'none'}:${lastRead.lastRead.read_at ?? ''}`
    : null
  const [dismissedLastReadKey, setDismissedLastReadKey] = useState<string | null>(null)
  const showLastRead = lastRead != null && lastReadKey !== dismissedLastReadKey

  const handleBackToQueue = useCallback(() => {
    // Leaving for the queue is navigation, not resolution (issue #3761): the
    // pending read stays server-side, so the unresolved selection is still
    // there when the reader comes back. Mark the bootstrap cache stale so the
    // next active use (returning to Roll) refetches instead of replaying a
    // snapshot captured before the roll. This avoids an eager HTTP request on
    // navigation while preserving the no-stale-pending guarantee.
    void invalidateRollBootstrapOnNavigation(queryClient)
    navigate('/queue')
  }, [navigate, queryClient])

  const setDieMutation = useSetDie()
  const resetDiceMutation = useResetDice()
  const rollMutation = useRoll()
  const dismissPendingMutation = useDismissPending()
  const overrideMutation = useOverrideRoll()
  const snoozeMutation = useSnooze()
  const moveToFrontMutation = useMoveToFront()
  const moveToBackMutation = useMoveToBack()
  const shuffleQueueMutation = useShuffleQueue()
  const rateMutation = useRate()
  const { setRestoreAction, clearRestoreAction } = useBugReportRestore()
  const tasteDiscoveries = useTasteDiscoveries()
  const { showToast } = useToast()
  const undo = useUndo()

  // A committed snooze closes the rating view and the action sheet, so an
  // exhausted authoritative refresh can only be reported from the page. The
  // toast carries the refresh-only retry, which reloads Roll state without
  // repeating the snooze.
  const retrySnoozeRefresh = snoozeMutation.retryRefresh
  const reportSnoozeRefreshFailed = useCallback((refreshError: unknown) => {
    showToast(
      `Snoozed, but the Roll pool did not refresh. ${getApiErrorDetail(refreshError)}`,
      'error',
      {
        label: 'Retry refresh',
        onClick: () => {
          void retrySnoozeRefresh()
        },
      },
    )
  }, [showToast, retrySnoozeRefresh])

  useRollBootstrapSync({
    state,
    bootstrap,
    scopedDieState: scopedDieState ?? null,
    isBootstrapError,
    bootstrapError,
    navigate,
  })

  const [resetDiceError, setResetDiceError] = useState('')

  const handleResetDice = useCallback(async () => {
    setResetDiceError('')
    try {
      await resetDiceMutation.mutate()
      state.setIsRolling(false)
      state.setIsRatingView(false)
      state.setRolledResult(null)
      state.setSelectedThreadId(null)
      state.setActiveRatingThread(null)
      state.setErrorMessage('')
      return true
    } catch (error: unknown) {
      setResetDiceError(getApiErrorDetail(error))
      return false
    }
  }, [resetDiceMutation, state])

  // Scoped eligible ids own the pool order (#4719). Bootstrap rows remain
  // the display-metadata source, but an eligible id absent from the bootstrap
  // slice (e.g. a die/eligibility update between the two independent reads)
  // is backfilled from the scoped issue cards instead of being silently
  // dropped: cards carry the thread identity (title, issue) needed to render
  // the face. Until the cards query settles, that face is simply not row
  // source yet — the same fallback-while-settling pattern as die-state.
  // thread_ids are parallel to issue_ids, so a thread may repeat; dedupe.
  const scopedPool = useMemo(() => {
    const poolThreads = bootstrap?.roll_pool ?? []
    if (!scopedEligibleIssueIds || scopedEligibleIssueIds.thread_ids == null) {
      return poolThreads
    }
    const byId = new Map(poolThreads.map((thread) => [thread.id, thread]))
    const cardByThreadId = new Map(
      (scopedIssueCards?.items ?? []).map((card) => [card.thread_id, card]),
    )
    return [...new Set(scopedEligibleIssueIds.thread_ids)]
      .flatMap((id): RollBootstrapThread[] => {
        const bootstrapThread = byId.get(id)
        if (bootstrapThread) return [bootstrapThread]
        const card = cardByThreadId.get(id)
        if (!card) return []
        return [{
          id,
          title: card.thread_title,
          format: '',
          issue_id: card.issue_id,
          issue_number: card.issue_number,
          tags: [],
        }]
      })
  }, [scopedEligibleIssueIds, scopedIssueCards, bootstrap?.roll_pool])

  useRollPendingSession({ state, bootstrap, rollPool: scopedPool })

  const rating = useRollRating({
    state,
    bootstrap,
    rateMutation,
    dismissPendingMutation,
    refetchBootstrap,
  })

  // Undoing a rating restores the snapshot the rating itself wrote, which is the
  // newest one while nothing else has been rated since (#3194). The list stays
  // disabled until a just-rated notice is on screen so Roll costs nothing at
  // rest, and the click path re-reads it before acting so a second rating inside
  // the snapshot query's stale window cannot undo two ratings at once.
  const undoSessionId = rating.lastRated ? bootstrap?.session_id ?? null : null
  const { data: undoSnapshots, refetch: refetchUndoSnapshots } = useSnapshots(undoSessionId)
  const latestUndoSnapshot = undoSnapshots?.snapshots[0]
  const canUndoLastRating =
    latestUndoSnapshot != null && latestUndoSnapshot.description !== 'Session start'

  const { mainDieRef, ratingViewTopRef } = useRollViewport({
    isRatingView: state.isRatingView,
  })

  // Entering the rating view unmounts the Roll CTA that held keyboard focus,
  // which drops focus to document.body and forces a keyboard user to re-tab
  // through the whole shell to reach the result. The rating region owns the
  // restore, so every entry path (roll, skip, read, stale read, recovery, and
  // pending-session hydration) is covered by one effect instead of a
  // per-caller timer (#3147).
  useEffect(() => {
    if (!state.isRatingView) return
    ratingViewTopRef.current?.focus()
  }, [state.isRatingView, ratingViewTopRef])

  const snooze = useRollSnooze({
    state,
    snoozeMutation,
    rerollMutation: rollMutation,
    enterRatingView: rating.enterRatingView,
    refetchBootstrap,
    onRefreshFailed: reportSnoozeRefreshFailed,
  })

  const actions = useRollActions({
    state,
    bootstrap,
    rollPool: scopedPool,
    navigate,
    mutations: {
      setDieMutation,
      rollMutation,
      snoozeMutation,
      moveToFrontMutation,
      moveToBackMutation,
      shuffleQueueMutation,
    },
    refetchBootstrap,
    enterRatingView: rating.enterRatingView,
    threadsApi,
    onSnoozeRefreshFailed: reportSnoozeRefreshFailed,
  })

  const modals = useRollModals({
    state,
    bootstrap,
    overrideMutation,
    enterRatingView: rating.enterRatingView,
    setRestoreAction,
    clearRestoreAction,
  })

  // The shuffle confirmation has to name the whole-queue blast radius, and the
  // Roll bootstrap only carries the die-sized roll_pool, so the authoritative
  // active-series total is fetched while the confirmation is actually open.
  const activeSeriesCount = useActiveSeriesCount(state.isShuffleOpen)

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
      state.suppressPendingAutoOpenRef.current = true
      rating.enterRatingView(response.thread_id, null, threadMetadata)
    } catch (error) {
      console.error('Set current issue failed:', error)
      throw error
    }
  }

  const handleUndoRating = async () => {
    const rated = rating.lastRated
    const sessionId = bootstrap?.session_id
    if (!rated || sessionId == null) return

    try {
      const freshSnapshots = await refetchUndoSnapshots()
      const snapshot = freshSnapshots.data?.snapshots[0]
      if (!snapshot || snapshot.description === 'Session start') {
        showToast('No undo point is recorded for this rating.', 'error')
        return
      }

      await undo.mutate({ sessionId, snapshotId: snapshot.id })
      showToast(`Rating for "${rated.title} ${rated.issueNumber}" has been undone`, 'success')
      // Drop the notice before the refresh lands: the restored state is the
      // one the reader asked for, and keeping a "you just rated" prompt up
      // over a state where the rating no longer exists is the stale read #3194.
      rating.clearLastRated()
      await invalidateAfterUndo(queryClient)
    } catch (error) {
      console.error('Undo failed:', error)
      showToast('Failed to undo rating. Please try again.', 'error')
    }
  }

  const ratingViewData = useRatingView({
    state,
    bootstrap,
    readerContextRequested: rating.readerContextRequested,
    readingContextRequested: rating.readingContextRequested,
    readingBoundariesRequested: rating.readingBoundariesRequested,
    readingOrders: rating.readingOrders,
    connectedThreads: rating.connectedThreads,
    onShowContext: () => rating.fetchReadingContext(state.activeRatingThread?.id ?? null),
    onShowBoundaries: () => rating.fetchReadingBoundaries(),
    readingOrdersIsLoading: rating.readingOrdersIsLoading,
    readingOrdersError: rating.readingOrdersError,
    connectedThreadsIsLoading: rating.connectedThreadsIsLoading,
    connectedThreadsError: rating.connectedThreadsError,
    rating,
    snooze,
    rateMutation,
    snoozeMutation,
    rerollMutation: rollMutation,
    onReroll: snooze.handleReroll,
    onResetDice: () => state.setIsDieModalOpen(true),
    dismissPendingMutation,
    ratingViewTopRef,
  })

  const snoozedThreads = bootstrap?.snoozed_threads ?? []
  // Scoped die drives the pool cutoff and 3D model when present; the
  // bootstrap-synced state remains the fallback while it settles or fails.
  const effectiveDie = scopedDieState?.die ?? state.currentDie
  const dieSize = effectiveDie || 6
  const filteredThreads = scopedPool.filter(
    (thread) =>
      !state.isRatingView || thread.id !== (state.selectedThreadId ? Number(state.selectedThreadId) : null),
  )
  const pool = filteredThreads.slice(0, dieSize)
  const displayDie = isDiceSide(effectiveDie) ? effectiveDie : 6
  const hasRollableContent = pool.length > 0 || snoozedThreads.length > 0
 
  if (isBootstrapLoading && !bootstrap && !isBootstrapError) {
    // A timed-out bootstrap stays pending through the shared retry policy
    // (issue #3429). Once an attempt has failed, say so and offer recovery
    // instead of holding a bare spinner until retries exhaust. isBootstrapRetrying
    // stays true across a user-initiated retry, so pressing Retry never drops
    // the user back onto the bare splash.
    if (isBootstrapRetrying) {
      return (
        <div className="min-h-screen flex flex-col items-center justify-center p-4">
          <div className="text-center space-y-4">
            <p
              role="status"
              className="text-center text-[var(--theme-text-muted)] font-black uppercase tracking-widest text-[10px]"
            >
              Still loading… your library is safe.
            </p>
            <button
              type="button"
              onClick={() => refetchBootstrap()}
              className="px-4 py-2 bg-[var(--theme-warning)]/20 border border-[var(--theme-warning)]/50 rounded-lg text-xs font-black uppercase tracking-widest text-[var(--theme-warning)] hover:bg-[var(--theme-warning)]/30 transition-colors"
            >
              Retry
            </button>
          </div>
        </div>
      )
    }
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
              className="px-4 py-2 bg-[var(--theme-warning)]/20 border border-[var(--theme-warning)]/50 rounded-lg text-xs font-black uppercase tracking-widest text-[var(--theme-warning)] hover:bg-[var(--theme-warning)]/30 transition-colors"
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
        onSetDie={actions.handleSetDie}
        onOpenOverride={modals.openOverrideModal}
        onOpenDieModal={() => state.setIsDieModalOpen(true)}
        onBackToQueue={handleBackToQueue}
        dieState={scopedDieState ?? null}
      />

      <ReadingModeLauncher />

      <div className="px-4 md:px-6 pt-4">
        <ReadingGraphProblemCard />
      </div>

      <div className="flex-1 flex flex-col min-h-0">
        {/* Rating mode is a page-level composition, not one giant generic
            rounded panel: the ambient glow stays as page atmosphere while the
            workspace keeps its own region framing (issue #2712). */}
        <div
          data-testid="roll-workspace"
          className={`flex-1 flex flex-col relative ${state.isRatingView ? '' : 'md:surface-panel md:rounded-xl'}`}
        >
          <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-72 h-72 md:w-80 md:h-80 bg-amber-900/15 rounded-full blur-[100px] md:blur-[120px] pointer-events-none"></div>
          <div className="flex-1 flex flex-col">
            {!state.isRatingView && hasRollableContent ? (
              <>
                <div
                  id="main-die-3d"
                  ref={mainDieRef}
                  onClick={actions.handleRoll}
                  onKeyDown={actions.handleKeyDown}
                  role="button"
                  tabIndex={0}
                  aria-label={displayDie === 2 ? "Flip the coin" : "Roll the dice"}
                  className={`dice-state-${state.diceState} relative z-10 cursor-pointer shrink-0 flex items-center justify-center rounded-full transition-all mt-4 md:mt-8 mx-auto active:scale-95`}
                  style={{ width: '200px', height: '200px' }}
                  data-testid="main-die-3d"
                >
                  <div className="w-full h-full main-die-optical-center">
                    <LazyDice3D
                      sides={displayDie}
                      value={Math.max(1, Math.min(state.rolledResult ?? 1, displayDie))}
                      isRolling={state.isRolling}
                      showValue={false}
                      color={0xffffff}
                      onRollComplete={() => state.setDiceState('rolled')}
                    />
                  </div>
                </div>
                <RollCta
                  isRolling={state.isRolling}
                  hasRolled={state.diceState !== 'idle'}
                  onRoll={actions.handleRoll}
                />
              </>
            ) : !state.isRatingView ? (
              <div aria-hidden="true" className="h-[200px] w-[200px] mx-auto mt-4 md:mt-8" />
            ) : (
              <RatingView data={ratingViewData} />
            )}

            {!state.isRatingView &&
              (lastRead ? (
                showLastRead ? (
                  <LastReadStrip
                    view={lastRead}
                    onDismiss={() => setDismissedLastReadKey(lastReadKey)}
                    onRollAgain={actions.handleRoll}
                    onUndo={handleUndoRating}
                    undoPending={undo.isPending}
                    canUndo={canUndoLastRating}
                  />
                ) : null
              ) : (
                <PostRateCopyPrompt
                  reference={rating.lastRated}
                  onDismiss={rating.clearLastRated}
                  onUndo={handleUndoRating}
                  undoPending={undo.isPending}
                  canUndo={canUndoLastRating}
                />
              ))}

            {!state.isRatingView && (
              <TasteDiscoveryCard
                discovery={tasteDiscoveries.current}
                onRespond={tasteDiscoveries.respond}
                onDismiss={tasteDiscoveries.dismiss}
              />
            )}

            <ThreadPool
              pool={pool}
              dieSize={dieSize}
              isRatingView={state.isRatingView}
              selectedThreadId={state.selectedThreadId}
              // Empty-pool explanation migration (#4719): the scoped eligible
              // resource carries the server-computed reason from the same
              // Option E inputs as bootstrap, so it is authoritative once
              // settled. Bootstrap remains the fallback while the scoped
              // query is pending or failed. The copy and CTA stay exactly the
              // same four-way variants `ThreadPool` already renders.
              emptyPoolReason={scopedEligibleIssueIds?.pool_reason ?? bootstrap?.pool_reason}

              snoozedThreads={snoozedThreads}
              snoozedCount={bootstrap?.snoozed_count ?? snoozedThreads.length}
              eligibleThreadIds={scopedEligibleIssueIds?.thread_ids ?? null}
              issueCards={scopedIssueCards ?? null}
              snoozedExpanded={state.snoozedExpanded}
              onThreadClick={actions.handleThreadClick}
              onUnsnooze={snooze.handleUnsnooze}
              onToggleSnoozed={() => state.setSnoozedExpanded(!state.snoozedExpanded)}

              onShuffle={actions.handleShufflePool}
              unsnoozeIsPending={false}
              shuffleIsPending={shuffleQueueMutation.isPending}
            />
          </div>
        </div>

        <div id="explosion-layer" className="explosion-wrap"></div>

        {state.isRatingView && <RollFooter />}

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
          currentDie={effectiveDie}
          onSetDie={actions.handleSetDie}
          onResetDice={handleResetDice}
          resetDicePending={resetDiceMutation.isPending}
          resetDiceError={resetDiceError}
          setDiePending={setDieMutation.isPending}
          isActionSheetOpen={state.isActionSheetOpen}
          selectedThread={state.selectedThread}
          pendingThreadId={bootstrap.pending_thread_id}
          onCloseActionSheet={() => state.setIsActionSheetOpen(false)}
          onAction={actions.handleAction}
          isSetCurrentIssueOpen={state.isSetCurrentIssueOpen}
          onCloseSetCurrentIssue={() => state.setIsSetCurrentIssueOpen(false)}
          onSetCurrentIssue={handleSetCurrentIssue}
          isShuffleOpen={state.isShuffleOpen}
          onShuffleConfirm={actions.performShuffle}
          onShuffleCancel={() => {
            state.setShuffleError('')
            state.setIsShuffleOpen(false)
          }}
          shufflePending={shuffleQueueMutation.isPending}
          shuffleError={state.shuffleError}
          seriesCount={activeSeriesCount ?? 0}
        />
      </div>
    </div>
  )
}