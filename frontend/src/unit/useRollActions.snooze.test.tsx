/**
 * Issue #3260 — the Roll pool action sheet's Snooze entry used to ignore the
 * series it was opened for. It fired the session's pending-thread snooze
 * unconditionally, so choosing any other pooled series either snoozed a
 * different series or failed with a 400 that `handleAction` swallowed into
 * `console.error` after the sheet had already closed. Either way the reader
 * saw the click "succeed" and nothing was recorded.
 */
import { act, renderHook } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { NavigateFunction } from 'react-router-dom'
import { useRollActions } from '../pages/RollPage/useRollActions'
import { useRollPageState } from '../pages/RollPage/useRollPageState'
import { SNOOZE_REQUIRES_PENDING_SERIES_REASON } from '../components/snoozeAvailability'
import type { SnoozeSessionResponse } from '../types'
import type { RollBootstrapResponse, RollBootstrapThread } from '../types/rollBootstrap'

function bootstrapWith(overrides: Partial<RollBootstrapResponse> = {}): RollBootstrapResponse {
  // SAFETY: the literal supplies every required bootstrap field; the spread only narrows them
  return {
    session_id: 1,
    user_id: 1,
    current_die: 6,
    manual_die: null,
    pending_thread_id: null,
    last_rolled_result: null,
    session_mode: null,
    active_thread: null,
    roll_pool: [],
    snoozed_threads: [],
    snoozed_count: 0,
    blocked_count: 0,
    blocked_threads: [],
    skipped_thread_ids: [],
    skipped_threads: [],
    stale_thread_count: 0,
    stale_thread: null,
    ...overrides,
  } as RollBootstrapResponse
}

function pooledThread(id: number): RollBootstrapThread {
  return { id, title: `Series ${id}`, format: 'Comic' }
}

interface HarnessOptions {
  bootstrap?: RollBootstrapResponse
  selectedThreadId?: number
  snoozeImpl?: () => Promise<SnoozeSessionResponse>
}

function renderActionSheet(options: HarnessOptions = {}) {
  const { bootstrap = bootstrapWith(), snoozeImpl } = options

  // SAFETY: the hook only awaits the result; the stub stands in for the API's empty 200 body
  const snoozeMutate = vi.fn(snoozeImpl ?? (() => Promise.resolve(undefined as SnoozeSessionResponse | undefined)))
  const unsnoozeMutate = vi.fn(() => Promise.resolve(undefined))
  const refetchBootstrap = vi.fn(() => Promise.resolve(bootstrap))

  const { result } = renderHook(() => {
    const state = useRollPageState()

    const actions = useRollActions({
      state,
      bootstrap,
      rollPool: bootstrap.roll_pool,
      // SAFETY: the hook only calls navigate in routing flows this test never triggers
      navigate: vi.fn() as NavigateFunction,
      mutations: {
        setDieMutation: { mutate: vi.fn(() => Promise.resolve()), isPending: false },
        clearManualDieMutation: { mutate: vi.fn(() => Promise.resolve()), isPending: false },
        rollMutation: { mutate: vi.fn(), isPending: false },
        snoozeMutation: { mutate: snoozeMutate, isPending: false },
        unsnoozeMutation: { mutate: unsnoozeMutate, isPending: false },
        skipMutation: { mutate: vi.fn(() => Promise.resolve(undefined)), isPending: false },
        unskipMutation: { mutate: vi.fn(() => Promise.resolve()), isPending: false },
        moveToFrontMutation: { mutate: vi.fn(() => Promise.resolve()), isPending: false },
        moveToBackMutation: { mutate: vi.fn(() => Promise.resolve()), isPending: false },
        shuffleQueueMutation: { mutate: vi.fn(() => Promise.resolve()), isPending: false },
      },
      refetchBootstrap,
      enterRatingView: vi.fn(() => Promise.resolve()),
      // SAFETY: the hook only calls setPending; the stub omits the rest of the API surface
      threadsApi: { setPending: vi.fn() } as never,
    })

    return { state, actions }
  })

  // `result` stays live so every assertion reads the latest render's closure.
  return { result, snoozeMutate, unsnoozeMutate, refetchBootstrap }
}

/** Select the pooled series whose action sheet the reader opened. */
function selectThread(
  result: { current: { state: ReturnType<typeof useRollPageState> } },
  threadId: number,
): void {
  act(() => {
    result.current.state.setSelectedThread(pooledThread(threadId))
  })
}

describe('Roll pool action sheet snooze (issue #3260)', () => {
  it('snoozes the rolled series and passes it as the expected pending thread', async () => {
    const { result, snoozeMutate, refetchBootstrap } = renderActionSheet({
      bootstrap: bootstrapWith({ pending_thread_id: 8 }),
    })
    selectThread(result, 8)

    await act(async () => {
      await result.current.actions.handleAction('snooze')
    })

    // The id doubles as `expectedPendingThreadId`; dropping it would disable the
    // hook's auth-failure recovery and ambiguous-failure reconciliation.
    expect(snoozeMutate).toHaveBeenCalledWith(8)
    expect(refetchBootstrap).toHaveBeenCalled()
  })

  it('never snoozes a different series when a pooled series was chosen', async () => {
    const { result, snoozeMutate } = renderActionSheet({
      bootstrap: bootstrapWith({ pending_thread_id: 7 }),
    })
    selectThread(result, 8)

    await act(async () => {
      await result.current.actions.handleAction('snooze')
    })

    expect(snoozeMutate).not.toHaveBeenCalled()
    expect(result.current.state.errorMessage).toBe(SNOOZE_REQUIRES_PENDING_SERIES_REASON)
  })

  it('explains the restriction instead of failing when nothing is rolled', async () => {
    const { result, snoozeMutate } = renderActionSheet({
      bootstrap: bootstrapWith({ pending_thread_id: null }),
    })
    selectThread(result, 8)

    await act(async () => {
      await result.current.actions.handleAction('snooze')
    })

    expect(snoozeMutate).not.toHaveBeenCalled()
    expect(result.current.state.errorMessage).toBe(SNOOZE_REQUIRES_PENDING_SERIES_REASON)
  })

  it('unsnoozes the selected series regardless of the pending thread', async () => {
    const { result, unsnoozeMutate, snoozeMutate } = renderActionSheet({
      bootstrap: bootstrapWith({ snoozed_threads: [pooledThread(8)], pending_thread_id: null }),
    })
    selectThread(result, 8)

    await act(async () => {
      await result.current.actions.handleAction('snooze')
    })

    expect(unsnoozeMutate).toHaveBeenCalledWith(8)
    expect(snoozeMutate).not.toHaveBeenCalled()
  })

  it('surfaces a failed snooze instead of only logging it', async () => {
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    const { result } = renderActionSheet({
      bootstrap: bootstrapWith({ pending_thread_id: 8 }),
      snoozeImpl: () => Promise.reject(new Error('snooze unavailable')),
    })
    selectThread(result, 8)

    await act(async () => {
      await result.current.actions.handleAction('snooze')
    })

    expect(errorSpy).toHaveBeenCalledWith('Action failed:', expect.any(Error))
    expect(result.current.state.errorMessage).toBe('snooze unavailable')
    errorSpy.mockRestore()
  })
})
