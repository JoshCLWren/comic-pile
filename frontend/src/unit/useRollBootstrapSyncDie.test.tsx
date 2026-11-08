import { renderHook } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { DieStateResponse } from '../generated/nativeV2Client'
import { useRollBootstrapSync } from '../pages/RollPage/useRollBootstrapSync'
import type { RollBootstrapResponse } from '../types/rollBootstrap'
import type { RollPageStateSetters } from '../pages/RollPage/useRollPageState'

const setCurrentDie = vi.fn<(die: number) => void>()
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

function dieStateWith(overrides: Partial<DieStateResponse> = {}): DieStateResponse {
  return {
    die: 20,
    ladder: [2, 4, 6, 8, 10, 12, 20],
    default_die: 6,
    last_roll: null,
    ...overrides,
  }
}

function stateSetters(): RollPageStateSetters {
  setCurrentDie.mockClear()
  setRolledResult.mockClear()
  setDiceState.mockClear()
  navigate.mockClear()
  return {
    setIsRolling: vi.fn(),
    setRolledResult,
    setSelectedThreadId: vi.fn(),
    setCurrentDie,
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
  scopedDieState: DieStateResponse | null | undefined,
) {
  // SAFETY: these die-sync cases never pass isBootstrapError true, so the hook never calls navigate (it only navigates on a 401); a no-op stub is safe.
  return renderHook(() =>
    useRollBootstrapSync({
      state: stateSetters(),
      bootstrap,
      scopedDieState,
      isBootstrapError: false,
      bootstrapError: null,
      navigate: navigate as never,
    }),
  )
}

describe('useRollBootstrapSync die surface (#4719)', () => {
  it('prefers the scoped die over bootstrap manual/current die', () => {
    renderSync(
      bootstrapWith({ manual_die: 12, current_die: 8 }),
      dieStateWith({ die: 20 }),
    )

    expect(setCurrentDie).toHaveBeenCalledWith(20)
  })

  it('falls back to bootstrap manual die while scoped state is unsettled', () => {
    renderSync(bootstrapWith({ manual_die: 12, current_die: 8 }), undefined)

    expect(setCurrentDie).toHaveBeenCalledWith(12)
  })

  it('falls back to bootstrap current die when no manual die is pinned', () => {
    renderSync(bootstrapWith({ manual_die: null, current_die: 8 }), null)

    expect(setCurrentDie).toHaveBeenCalledWith(8)
  })

  it('keeps the rolled projection bootstrap-only so a stale cross-session roll never lights', () => {
    renderSync(
      bootstrapWith({ last_rolled_result: null }),
      dieStateWith({
        die: 20,
        last_roll: {
          thread_id: 30,
          issue_id: 300,
          issue_number: '1',
          result: 5,
          die: 20,
          rolled_at: '2026-11-01T10:00:00.000Z',
        },
      }),
    )

    expect(setCurrentDie).toHaveBeenCalledWith(20)
    expect(setRolledResult).not.toHaveBeenCalled()
    expect(setDiceState).not.toHaveBeenCalled()
  })

  it('still projects the bootstrap pending roll when one exists', () => {
    renderSync(
      bootstrapWith({ last_rolled_result: 3 }),
      dieStateWith({
        die: 20,
        last_roll: {
          thread_id: 30,
          issue_id: 300,
          issue_number: '1',
          result: 5,
          die: 20,
          rolled_at: '2026-11-01T10:00:00.000Z',
        },
      }),
    )

    expect(setCurrentDie).toHaveBeenCalledWith(20)
    expect(setRolledResult).toHaveBeenCalledWith(3)
    expect(setDiceState).toHaveBeenCalledWith('rolled')
  })

  it('does not synthesize a die when both surfaces are absent', () => {
    renderSync(undefined, undefined)

    expect(setCurrentDie).not.toHaveBeenCalled()
    expect(setRolledResult).not.toHaveBeenCalled()
    expect(setDiceState).not.toHaveBeenCalled()
  })
})
