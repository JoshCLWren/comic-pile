import { vi } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useRollPendingSync } from '../pages/QueuePage/useRollPendingSync'
import type { RollBootstrapResponse } from '../types/rollBootstrap'

function bootstrap(overrides: Partial<RollBootstrapResponse> = {}): RollBootstrapResponse {
  return {
    session_id: 1,
    user_id: 1,
    pending_thread_id: 99,
    last_rolled_result: 3,
    // SAFETY: the mode payload is not read by the pending sync
    session_mode: 'manual' as never,
    active_thread: null,
    roll_pool: [],
    snoozed_threads: [],
    snoozed_count: 0,
    skipped_thread_ids: [],
    skipped_threads: [],
    ...overrides,
  }
}

describe('useRollPendingSync', () => {
  it('has no Roll state until the bootstrap resolves', () => {
    const { result: absent } = renderHook(() =>
      useRollPendingSync({ rollBootstrap: null, refetchQueue: vi.fn() }),
    )
    const { result: undef } = renderHook(() =>
      useRollPendingSync({ rollBootstrap: undefined, refetchQueue: vi.fn() }),
    )

    expect(absent.current.rollState).toBeUndefined()
    expect(undef.current.rollState).toBeUndefined()
  })

  it('derives the pending thread and snoozed series from the Roll bootstrap', () => {
    const { result } = renderHook(() =>
      useRollPendingSync({
        rollBootstrap: bootstrap({
          pending_thread_id: 99,
          snoozed_threads: [{ id: 5, title: 'Saga', format: 'Comic' }],
        }),
        refetchQueue: vi.fn(),
      }),
    )

    expect(result.current.rollState?.pending_thread_id).toBe(99)
    expect(result.current.rollState?.snoozed_thread_ids).toEqual([5])
  })

  it('uses the complete snoozed id list rather than the 20-row display summary', () => {
    const displayed = Array.from({ length: 20 }, (_, index) => ({
      id: index + 1,
      title: `Series ${index + 1}`,
      format: 'Comic',
    }))
    const allIds = Array.from({ length: 25 }, (_, index) => index + 1)
    const { result } = renderHook(() =>
      useRollPendingSync({
        rollBootstrap: bootstrap({ snoozed_threads: displayed, snoozed_thread_ids: allIds, snoozed_count: 25 }),
        refetchQueue: vi.fn(),
      }),
    )

    expect(result.current.rollState?.snoozed_thread_ids).toEqual(allIds)
  })

  it('treats a null pending_thread_id as authoritative (post-dismiss scenario)', () => {
    const { result } = renderHook(() =>
      useRollPendingSync({
        rollBootstrap: bootstrap({ pending_thread_id: null }),
        refetchQueue: vi.fn(),
      }),
    )

    expect(result.current.rollState?.pending_thread_id).toBeNull()
  })

  it('refetches the queue on update without any session call', async () => {
    const refetchQueue = vi.fn().mockResolvedValue(undefined)
    const { result } = renderHook(() =>
      useRollPendingSync({ rollBootstrap: bootstrap(), refetchQueue }),
    )

    await result.current.onUpdated()
    await result.current.onRefetchRollState()

    expect(refetchQueue).toHaveBeenCalledTimes(1)
  })
})
