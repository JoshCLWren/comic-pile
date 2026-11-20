import { vi } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useRollPendingSync } from '../pages/QueuePage/useRollPendingSync'
import type { RollBootstrapResponse } from '../types/rollBootstrap'
import type { SessionCurrent } from '../types'

// SAFETY: vi.mocked returns strict hook types; cast to any for flexible test stubs
const mockRefetchSession = () => vi.fn()
const mockRefetchQueue = () => vi.fn()

describe('useRollPendingSync', () => {
  it('returns session when rollBootstrap is null', () => {
    const mockSession: SessionCurrent = {
      id: 1,
      current_die: 6,
      pending_thread_id: 42,
      snoozed_threads: [],
    }

    const { result } = renderHook(() =>
      useRollPendingSync({
        rollBootstrap: null,
        session: mockSession,
        refetchSession: mockRefetchSession(),
        refetchQueue: mockRefetchQueue(),
      }),
    )

    expect(result.current.session).toEqual(mockSession)
  })

  it('returns session unchanged when rollBootstrap is absent (undefined)', () => {
    const mockSession: SessionCurrent = {
      id: 1,
      current_die: 6,
      pending_thread_id: 42,
      snoozed_threads: [],
    }

    const { result } = renderHook(() =>
      useRollPendingSync({
        // SAFETY: undefined bootstrap simulates absent data for this test
        rollBootstrap: undefined as any,
        session: mockSession,
        refetchSession: mockRefetchSession(),
        refetchQueue: mockRefetchQueue(),
      }),
    )

    expect(result.current.session).toEqual(mockSession)
  })

  it('uses rollBootstrap.pending_thread_id as authoritative when bootstrap data exists', () => {
    const mockSession: SessionCurrent = {
      id: 1,
      current_die: 6,
      pending_thread_id: 42,
      snoozed_threads: [],
    }

    const mockBootstrap: RollBootstrapResponse = {
      session_id: 1,
      user_id: 1,
      pending_thread_id: 99,
      last_rolled_result: 3,
      // SAFETY: 'manual' is a valid session mode for test data
      session_mode: 'manual' as any,
      active_thread: null,
      roll_pool: [],
      snoozed_threads: [],
      snoozed_count: 0,
      skipped_thread_ids: [],
      skipped_threads: [],
    }

    const { result } = renderHook(() =>
      useRollPendingSync({
        rollBootstrap: mockBootstrap,
        session: mockSession,
        refetchSession: mockRefetchSession(),
        refetchQueue: mockRefetchQueue(),
      }),
    )

    expect(result.current.session).toEqual({
      ...mockSession,
      pending_thread_id: 99,
    })
  })

  it('uses rollBootstrap.pending_thread_id even when it is null (post-dismiss scenario)', () => {
    // This tests the fix for the bug where after dismissing a pending read,
    // bootstrap reports null while session cache still has the old ID,
    // and Queue Snooze should be disabled (not incorrectly enabled for old series)
    const mockSession: SessionCurrent = {
      id: 1,
      current_die: 6,
      pending_thread_id: 42,
      snoozed_threads: [],
    }

    const mockBootstrap: RollBootstrapResponse = {
      session_id: 1,
      user_id: 1,
      pending_thread_id: null, // Bootstrap reports no pending thread after dismissal
      last_rolled_result: null,
      // SAFETY: 'manual' is a valid session mode for test data
      session_mode: 'manual' as any,
      active_thread: null,
      roll_pool: [],
      snoozed_threads: [],
      snoozed_count: 0,
      skipped_thread_ids: [],
      skipped_threads: [],
    }

    const { result } = renderHook(() =>
      useRollPendingSync({
        rollBootstrap: mockBootstrap,
        session: mockSession,
        refetchSession: mockRefetchSession(),
        refetchQueue: mockRefetchQueue(),
      }),
    )

    // The session should have pending_thread_id = null from bootstrap
    expect(result.current.session).toEqual({
      ...mockSession,
      pending_thread_id: null,
    })
  })

  it('returns undefined when session is undefined', () => {
    const mockBootstrap: RollBootstrapResponse = {
      session_id: 1,
      user_id: 1,
      pending_thread_id: 99,
      last_rolled_result: 3,
      // SAFETY: 'manual' is a valid session mode for test data
      session_mode: 'manual' as any,
      active_thread: null,
      roll_pool: [],
      snoozed_threads: [],
      snoozed_count: 0,
      skipped_thread_ids: [],
      skipped_threads: [],
    }

    const { result } = renderHook(() =>
      useRollPendingSync({
        rollBootstrap: mockBootstrap,
        session: undefined,
        refetchSession: mockRefetchSession(),
        refetchQueue: mockRefetchQueue(),
      }),
    )

    expect(result.current.session).toBeUndefined()
  })
})