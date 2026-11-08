import { renderHook } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { useRollBootstrapSync } from '../pages/RollPage/useRollBootstrapSync'
import type { RollBootstrapResponse } from '../types/rollBootstrap'
import type { RollPageStateSetters } from '../pages/RollPage/useRollPageState'

// Die selection is render-derived in `RollPage` (#4352); this hook only
// projects the bootstrap pending roll. `setCurrentDie` no longer exists on
// the page state (removed from `useRollPageState`), so the rolled-projection
// cases below assert the hook never touches any die setter — the type
// itself is the guard, and the absence of a die argument is asserted by
// `renderSync` below.

const setRolledResult = vi.fn<(result: number | null) => void>()
const setDiceState = vi.fn<(state: string) => void>()
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

function stateSetters(): RollPageStateSetters {
  setRolledResult.mockClear()
  setDiceState.mockClear()
  navigate.mockClear()
  return {
    setIsRolling: vi.fn(),
    setRolledResult,
    setSelectedThreadId: vi.fn(),
    setDiceState,
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

function renderSync(
  bootstrap: RollBootstrapResponse | null | undefined,
) {
  // SAFETY: these cases never pass isBootstrapError true, so the hook never calls navigate (it only navigates on a 401); a no-op stub is safe.
  return renderHook(() =>
    useRollBootstrapSync({
      state: stateSetters(),
      bootstrap,
      isBootstrapError: false,
      bootstrapError: null,
      navigate: navigate as never,
    }),
  )
}

describe('useRollBootstrapSync rolled projection (#4352)', () => {
  it('keeps the rolled projection bootstrap-only and never syncs a die', () => {
    renderSync(bootstrapWith({ last_rolled_result: null }))

    expect(setRolledResult).not.toHaveBeenCalled()
    expect(setDiceState).not.toHaveBeenCalled()
  })

  it('still projects the bootstrap pending roll when one exists', () => {
    renderSync(bootstrapWith({ last_rolled_result: 3 }))

    expect(setRolledResult).toHaveBeenCalledWith(3)
    expect(setDiceState).toHaveBeenCalledWith('rolled')
  })

  it('does not synthesize a rolled state when bootstrap is absent', () => {
    renderSync(undefined)

    expect(setRolledResult).not.toHaveBeenCalled()
    expect(setDiceState).not.toHaveBeenCalled()
  })
})
