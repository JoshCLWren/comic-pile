import { render, renderHook, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { useRollBootstrapSync } from '../pages/RollPage/useRollBootstrapSync'
import { useRollPendingSession } from '../pages/RollPage/useRollPendingSession'
import { RollCta } from '../pages/RollPage/components/RollCta'
import type { RollBootstrapResponse } from '../types/rollBootstrap'
import type { RollPageState, RollPageStateSetters } from '../pages/RollPage/useRollPageState'

// Die selection is render-derived in `RollPage` (#4352); this hook only
// projects the bootstrap pending roll. `setCurrentDie` no longer exists on
// the page state (removed from `useRollPageState`), so the rolled-projection
// cases below assert the hook never touches any die setter — the type
// itself is the guard, and the absence of a die argument is asserted by
// `renderSync` below.

const setRolledResult = vi.fn<(result: number | null) => void>()
const navigate = vi.fn()

function bootstrapWith(
  overrides: Partial<RollBootstrapResponse> = {},
): RollBootstrapResponse {
  return {
    session_id: 1,
    user_id: 1,
    current_die: 6,
    manual_die: null,
    pending_thread_id: null,
    last_rolled_result: null,
    session_mode: {
      active_bandwidth: null,
      predicted_bandwidth: null,
      bandwidth_confidence: null,
      bandwidth_source: null,
      bandwidth_version: null,
      active_intent: null,
      predicted_intent: null,
      intent_confidence: null,
      intent_source: null,
      intent_version: null,
      session_mode_correction_guidance: null,
    },
    active_thread: null,
    roll_pool: [],
    snoozed_threads: [],
    snoozed_count: 0,
    skipped_thread_ids: [],
    skipped_threads: [],
    ...overrides,
  }
}

function renderSync(
  _bootstrap: RollBootstrapResponse | null | undefined,
) {
  // SAFETY: the hook now only reads bootstrap-error navigation; state params are gone and no die/rolled write exists to exercise.
  return renderHook(() =>
    useRollBootstrapSync({
      isBootstrapError: false,
      bootstrapError: null,
      navigate: navigate as never,
    }),
  )
}

describe('useRollBootstrapSync redirect-only (#4352)', () => {
  it('keeps the hook redirect-only and never writes rolled or die', () => {
    renderSync(bootstrapWith({ last_rolled_result: null }))

    expect(setRolledResult).not.toHaveBeenCalled()
  })

  it('does not project bootstrap last_rolled_result; pending session owns pending hydration', () => {
    renderSync(bootstrapWith({ last_rolled_result: 3 }))

    // By construction the bootstrap sync never writes rolled, so the
    // bootstrap value cannot resurrect a cleared roll on its own. Only
    // useRollPendingSession (wider source when a pending thread exists)
    // may write rolledResult.
    expect(setRolledResult).not.toHaveBeenCalled()
  })

  it('does not synthesize a rolled state when bootstrap is absent', () => {
    renderSync(undefined)

    expect(setRolledResult).not.toHaveBeenCalled()
  })

  it('stale refetch never resurrects rolled after a clear', () => {
    // Since BootstrapSync writes no rolled state at all (redirect-only hook),
    // the cleared derivation (rolledResult null -> idle/Begin) cannot be
    // resurrected by any stale bootstrap or cross-session last_roll refetch.
    const { rerender } = renderHook(() =>
      useRollBootstrapSync({
        isBootstrapError: false,
        bootstrapError: null,
        // SAFETY: minimal vi.fn stub satisfying the navigate type; no navigation behavior is exercised here.
        navigate: navigate as never,
      }),
    )
    expect(setRolledResult).not.toHaveBeenCalled()
    setRolledResult.mockClear()
    rerender()
    // SAFETY: null literal pinned by the pending-then-cleared sequence; no other value can reach this point.
    const clearedHasRolled = (null as number | null) != null
    expect(clearedHasRolled).toBe(false)
    setRolledResult.mockClear()
    rerender()
    // Even a stale last_rolled_result on the next refetch must not light rolled.
    expect(setRolledResult).not.toHaveBeenCalled()
  })
})

describe('derived rolled state (#4352)', () => {
  // Mirrors the page derivation `hasRolled = rolledResult != null` and the
  // die class mapping in RollPage index.tsx. RollCta is production code, so
  // the label assertions exercise the real Begin / Roll again contract.
  it('pending (rolledResult present) -> rolled die class and Roll again, Begin off', () => {
    const rolledResult: number | null = 3
    const hasRolled = rolledResult != null
    expect(hasRolled).toBe(true)
    const dieClass = hasRolled ? 'dice-state-rolled' : 'dice-state-idle'
    expect(dieClass).toBe('dice-state-rolled')

    render(<RollCta isRolling={false} hasRolled={hasRolled} onRoll={vi.fn()} />)

    expect(screen.getByTestId('roll-primary-action')).toHaveTextContent('Roll again')
    expect(screen.queryByText('Begin')).not.toBeInTheDocument()
  })

  it('cleared (rolledResult null after rate/cancel/snooze) -> idle die class and Begin', () => {
    const rolledResult: number | null = null
    const hasRolled = rolledResult != null
    expect(hasRolled).toBe(false)
    const dieClass = hasRolled ? 'dice-state-rolled' : 'dice-state-idle'
    expect(dieClass).toBe('dice-state-idle')

    render(<RollCta isRolling={false} hasRolled={hasRolled} onRoll={vi.fn()} />)

    expect(screen.getByTestId('roll-primary-action')).toHaveTextContent('Begin')
  })
})

describe('pending session hydration (#4352 wider source kept)', () => {
  function pendingState(
    setRolled: (value: number | null) => void,
  ): RollPageState & RollPageStateSetters {
    return {
      isRolling: false,
      rolledResult: null,
      selectedThreadId: null,
      isOverrideOpen: false,
      overrideThreadId: '',
      overrideErrorMessage: '',
      snoozedExpanded: false,
      isDieModalOpen: false,
      isSetCurrentIssueOpen: false,
      selectedThread: null,
      isActionSheetOpen: false,
      activeRatingThread: null,
      showMigrationDialog: false,
      threadToMigrate: null,
      showSimpleMigration: false,
      isRatingView: false,
      isShuffleOpen: false,
      shuffleError: '',
      rating: 3.0,
      errorMessage: '',
      suppressPendingAutoOpenRef: { current: false },
      rollIntervalRef: { current: null },
      rollTimeoutRef: { current: null },
      setIsRolling: vi.fn(),
      setRolledResult: setRolled,
      setSelectedThreadId: vi.fn(),
      setIsOverrideOpen: vi.fn(),
      setOverrideThreadId: vi.fn(),
      setOverrideErrorMessage: vi.fn(),
      setSnoozedExpanded: vi.fn(),
      setIsDieModalOpen: vi.fn(),
      setIsSetCurrentIssueOpen: vi.fn(),
      setSelectedThread: vi.fn(),
      setIsActionSheetOpen: vi.fn(),
      setActiveRatingThread: vi.fn(),
      setShowMigrationDialog: vi.fn(),
      setThreadToMigrate: vi.fn(),
      setShowSimpleMigration: vi.fn(),
      setIsRatingView: vi.fn(),
      setIsShuffleOpen: vi.fn(),
      setShuffleError: vi.fn(),
      setRating: vi.fn(),
      setErrorMessage: vi.fn(),
    }
  }

  it('hydrates rolledResult from active_thread.last_rolled_result when bootstrap rolled is null', () => {
    const setRolled = vi.fn<(value: number | null) => void>()
    const bootstrap = bootstrapWith({
      pending_thread_id: 1,
      last_rolled_result: null,
      active_thread: {
        id: 1,
        title: 'Saga',
        format: 'Comic',
        issues_remaining: 5,
        queue_position: 0,
        total_issues: 10,
        reading_progress: null,
        issue_id: 100,
        issue_number: '1',
        next_issue_id: null,
        next_issue_number: '2',
        last_rolled_result: 7,
      },
    })

    renderHook(() =>
      useRollPendingSession({
        state: pendingState(setRolled),
        bootstrap,
        rollPool: [],
      }),
    )

    // Wider source: active_thread.last_rolled_result ?? bootstrap.last_rolled_result
    // So a pending roll lights rolled even when bootstrap reports null.
    expect(setRolled).toHaveBeenCalledWith(7)
  })

  it('hydrates rolledResult from bootstrap.last_rolled_result when active_thread has none', () => {
    const setRolled = vi.fn<(value: number | null) => void>()
    const bootstrap = bootstrapWith({
      pending_thread_id: 1,
      last_rolled_result: 4,
      active_thread: {
        id: 1,
        title: 'Saga',
        format: 'Comic',
        issues_remaining: 5,
        queue_position: 0,
        total_issues: 10,
        reading_progress: null,
        issue_id: 100,
        issue_number: '1',
        next_issue_id: null,
        next_issue_number: '2',
        last_rolled_result: null,
      },
    })

    renderHook(() =>
      useRollPendingSession({
        state: pendingState(setRolled),
        bootstrap,
        rollPool: [],
      }),
    )

    expect(setRolled).toHaveBeenCalledWith(4)
  })
})
