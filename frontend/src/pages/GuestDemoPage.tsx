import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import LazyDice3D from '../../components/LazyDice3D'
import { useGuestDemoRoll } from '../../hooks/useGuestDemo'
import { useGuestDemoBootstrap } from '../../hooks/useGuestDemo'
import { useRollPageState } from '../RollPage/useRollPageState'
import { ThreadPool } from '../RollPage/components/ThreadPool'
import { RollCta } from '../RollPage/components/RollCta'
import { PostRateCopyPrompt } from '../RollPage/components/PostRateCopyPrompt'
import { RatingView } from '../RollPage/components/RatingView'
import { useRatingView } from '../RollPage/useRatingView'
import { useRollRating } from '../RollPage/useRollRating'
import { useRollSnooze } from '../RollPage/useRollSnooze'
import { useRollActions } from '../RollPage/useRollActions'
import { useRollModals } from '../RollPage/useRollModals'
import { useRollDependencies } from '../RollPage/useRollDependencies'
import { useRollViewport } from '../RollPage/useRollViewport'
import { useRollBootstrapSync } from '../RollPage/useRollBootstrapSync'
import { useRollPendingSession } from '../RollPage/useRollPendingSession'
import { useRollPageState as UseRollPageState } from '../RollPage/useRollPageState'
import { useRollModals as UseRollModals } from '../RollPage/useRollModals'
import { useRollActions as UseRollActions } from '../RollPage/useRollActions'
import { useRollRating as UseRollRating } from '../RollPage/useRollRating'
import { useRollSnooze as UseRollSnooze } from '../RollPage/useRollSnooze'
import { useRollDependencies as UseRollDependencies } from '../RollPage/useRollDependencies'
import { useRollViewport as UseRollViewport } from '../RollPage/useRollViewport'
import { useRollBootstrapSync as UseRollBootstrapSync } from '../RollPage/useRollBootstrapSync'
import { useRollPendingSession as UseRollPendingSession } from '../RollPage/useRollPendingSession'
import { useRatingView as UseRatingView } from '../RollPage/useRatingView'
import { useTasteDiscoveries } from '../../hooks/useTasteDiscoveries'
import { useBugReportRestore } from '../../contexts/useBugReportRestore'
import { getApiErrorDetail, getApiErrorStatus } from '../../utils/apiError'
import { isDiceSide } from '../../components/diceTypes'
import { FEATURES } from '../../config/features'
import type { ThreadMetadata } from '../RollPage/types'

/**
 * Guest demo page for unauthenticated users.
 * Provides a single seeded sample roll experience before signup.
 */
export default function GuestDemoPage() {
  const navigate = useNavigate()
  const [hasRolled, setHasRolled] = useState(false)
  const [showSignupPrompt, setShowSignupPrompt] = useState(false)
  
  // Guest demo API hooks
  const { data: bootstrap, refetch: refetchBootstrap, isPending: isBootstrapLoading, isError: isBootstrapError, error: bootstrapError } = useGuestDemoBootstrap()
  const rollMutation = useGuestDemoRoll()
  
  // Reuse RollPage state management but for demo context
  const state = UseRollPageState()
  const tasteDiscoveries = useTasteDiscoveries()
  const { setRestoreAction, clearRestoreAction } = useBugReportRestore()
  
  // Demo-specific mutations
  const enterRatingView = useCallback((threadId: number, result: number | null, metadata: ThreadMetadata) => {
    setHasRolled(true)
    setShowSignupPrompt(true)
    state.setIsRatingView(true)
    state.setSelectedThreadId(threadId)
    state.setRolledResult(result)
  }, [state])
  
  // Sync demo bootstrap data
  useRollBootstrapSync({
    state,
    bootstrap,
    isBootstrapError,
    bootstrapError,
    navigate,
  })
  
  const rollPool = bootstrap?.roll_pool ?? []
  const dieSize = state.currentDie || 6
  const filteredThreads = rollPool.filter(
    (thread) =>
      !state.isRatingView || thread.id !== (state.selectedThreadId ? Number(state.selectedThreadId) : null),
  )
  const pool = filteredThreads.slice(0, dieSize)
  const displayDie = isDiceSide(state.currentDie) ? state.currentDie : 6
  const hasRollableContent = pool.length > 0
  
  // Handle demo roll
  const handleDemoRoll = useCallback(async () => {
    try {
      const response = await rollMutation.mutateAsync()
      if (!response) return
      
      const threadMetadata: ThreadMetadata = {
        id: response.thread_id,
        title: response.title,
        format: response.format,
        issues_remaining: response.issues_remaining,
        queue_position: response.queue_position,
        total_issues: response.total_issues,
        reading_progress: response.reading_progress,
        issue_id: response.issue_id,
        issue_number: response.issue_number,
        next_issue_id: response.next_issue_id,
        next_issue_number: response.next_issue_number,
        last_rolled_result: response.result,
      }
      
      state.setRolledResult(response.result)
      enterRatingView(response.thread_id, response.result, threadMetadata)
    } catch (error) {
      state.setErrorMessage(getApiErrorDetail(error))
    }
  }, [rollMutation, state, enterRatingView])
  
  // Handle signup
  const handleSignup = useCallback(() => {
    navigate('/register')
  }, [navigate])
  
  // Handle login
  const handleLogin = useCallback(() => {
    navigate('/login')
  }, [navigate])
  
  // Handle continue as guest (for testing/demo purposes)
  const handleContinueAsGuest = useCallback(() => {
    setShowSignupPrompt(false)
    // Reset for another demo roll
    state.setIsRatingView(false)
    state.setSelectedThreadId(null)
    state.setRolledResult(null)
  }, [state])
  
  if (isBootstrapLoading && !bootstrap && !isBootstrapError) {
    return (
      <div className="text-center py-10 text-stone-500 font-black uppercase tracking-widest text-[10px]">
        Loading demo...
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
          <h2 className="text-xl font-black text-stone-300 uppercase tracking-wider">Demo Error</h2>
          <p className="text-sm text-stone-400">{errorDetail}</p>
          <button
            onClick={() => refetchBootstrap()}
            className="px-4 py-2 bg-amber-600/20 border border-amber-600/50 rounded-lg text-xs font-black uppercase tracking-widest text-amber-500 hover:bg-amber-600/30 transition-colors"
          >
            Retry
          </button>
        </div>
      </div>
    )
  }
  
  return (
    <div className="min-h-screen flex flex-col bg-gradient-to-br from-amber-900/5 to-orange-900/5">
      {/* Demo header */}
      <div className="p-4 text-center border-b border-amber-800/20">
        <h1 className="text-lg font-black text-amber-400 uppercase tracking-wider">Comic Pile Demo</h1>
        <p className="text-xs text-amber-600/70 mt-1">Experience the magic of comic discovery</p>
      </div>
      
      <div className="flex-1 flex flex-col min-h-0">
        <div className="flex-1 flex flex-col relative md:surface-panel md:rounded-xl">
          <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-72 h-72 bg-amber-900/15 rounded-full blur-[100px] md:blur-[120px] pointer-events-none"></div>
          <div className="flex-1 flex flex-col">
            {!state.isRatingView && hasRollableContent ? (
              <>
                <div
                  id="main-die-3d"
                  onClick={handleDemoRoll}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      handleDemoRoll()
                    }
                  }}
                  role="button"
                  tabIndex={0}
                  aria-label="Roll the dice for demo"
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
                <RollCta
                  isRolling={state.isRolling}
                  hasRolled={state.diceState !== 'idle'}
                  onRoll={handleDemoRoll}
                />
              </>
            ) : !state.isRatingView ? (
              <div aria-hidden="true" className="h-[200px] w-[200px] mx-auto mt-4 md:mt-8" />
            ) : (
              <RatingView 
                data={{
                  activeThread: state.selectedThread,
                  isLoading: false,
                  error: null,
                  readerContext: null,
                  readingContext: null,
                  readingBoundaries: null,
                  readingOrders: null,
                  connectedThreads: null,
                  onRate: () => {},
                  onSnooze: () => {},
                  onDismiss: () => {},
                  onSkip: () => {},
                  rateMutation: { mutate: () => {}, isPending: false },
                  snoozeMutation: { mutate: () => {}, isPending: false },
                  dismissPendingMutation: { mutate: () => {}, isPending: false },
                  skipMutation: { mutate: () => {}, isPending: false },
                }} 
              />
            )}
            
            {/* Demo-specific prompts */}
            {showSignupPrompt && (
              <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
                <div className="surface-modal p-6 max-w-md mx-4 text-center">
                  <div className="text-4xl mb-4">🎲</div>
                  <h2 className="text-xl font-black text-stone-300 uppercase tracking-wider mb-2">
                    Great Roll!
                  </h2>
                  <p className="text-sm text-stone-400 mb-6">
                    You've experienced the ComicPile magic! Ready to build your permanent collection?
                  </p>
                  <div className="space-y-3">
                    <button
                      onClick={handleSignup}
                      className="w-full px-4 py-3 bg-amber-600 hover:bg-amber-700 rounded-lg text-sm font-black uppercase tracking-wider transition-colors"
                    >
                      Sign Up Free
                    </button>
                    <button
                      onClick={handleLogin}
                      className="w-full px-4 py-3 border border-amber-600/50 text-amber-500 hover:bg-amber-600/20 rounded-lg text-sm font-black uppercase tracking-wider transition-colors"
                    >
                      Log In
                    </button>
                    <button
                      onClick={handleContinueAsGuest}
                      className="w-full px-4 py-3 text-stone-400 hover:text-stone-300 rounded-lg text-sm font-black uppercase tracking-wider transition-colors"
                    >
                      Try Another Demo
                    </button>
                  </div>
                </div>
              </div>
            )}
            
            {/* Demo pool */}
            {pool.length > 0 && !state.isRatingView && (
              <ThreadPool
                pool={pool}
                blockedThreads={[]}
                blockingDependencyMap={{}}
                dieSize={dieSize}
                isRatingView={state.isRatingView}
                selectedThreadId={state.selectedThreadId}
                staleThread={null}
                staleThreadCount={0}
                snoozedThreads={[]}
                snoozedExpanded={false}
                blockedExpanded={false}
                skippedThreads={[]}
                skippedExpanded={false}
                onThreadClick={() => {}}
                onUnsnooze={() => {}}
                onUnskip={() => {}}
                onReadStale={() => {}}
                onToggleSnoozed={() => {}}
                onToggleSkipped={() => {}}
                onToggleBlocked={() => {}}
                onShuffle={() => {}}
                unsnoozeIsPending={false}
                unskipIsPending={false}
                shuffleIsPending={false}
              />
            )}
          </div>
        </div>
      </div>
      
      {/* Demo footer */}
      <div className="p-4 text-center border-t border-amber-800/20">
        <p className="text-xs text-amber-600/70">
          Demo data is temporary and will not be saved
        </p>
      </div>
    </div>
  )
}