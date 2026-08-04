import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ToastProvider } from '../contexts/ToastProvider'
import {
  isAmbiguousNetworkFailure,
  publishRollBootstrap,
  reconcileAmbiguousRollMutation,
  ROLL_BOOTSTRAP_RECONCILED_EVENT,
} from '../hooks/rollMutationReconciliation'
import { useRollBootstrap } from '../hooks/useRollBootstrap'
import { rollBootstrapApi } from '../services/rollBootstrapApi'
import type { RollBootstrapResponse } from '../types/rollBootstrap'

vi.mock('../services/rollBootstrapApi', () => ({
  rollBootstrapApi: {
    get: vi.fn(),
  },
}))

const mockedBootstrap = vi.mocked(rollBootstrapApi.get)

const bootstrapState = (
  currentDie: RollBootstrapResponse['current_die'],
  pendingThreadId: number | null,
): RollBootstrapResponse => ({
  session_id: 1,
  user_id: 1,
  current_die: currentDie,
  manual_die: null,
  pending_thread_id: pendingThreadId,
  last_rolled_result: pendingThreadId === null ? null : 1,
  active_thread: null,
  roll_pool: [],
  snoozed_threads: [],
  snoozed_count: 0,
  blocked_count: 0,
  blocked_threads: [],
  stale_thread_count: 0,
  stale_thread: null,
})

beforeEach(() => {
  mockedBootstrap.mockReset()
  localStorage.clear()
})

describe('Roll mutation reconciliation', () => {
  it('classifies only response-less timeout and network failures as ambiguous', () => {
    expect(isAmbiguousNetworkFailure(null)).toBe(false)
    expect(isAmbiguousNetworkFailure('timeout')).toBe(false)
    expect(isAmbiguousNetworkFailure({ response: { status: 500 }, code: 'ECONNABORTED' })).toBe(false)
    expect(isAmbiguousNetworkFailure({ code: 'ECONNABORTED' })).toBe(true)
    expect(isAmbiguousNetworkFailure({ code: 'ETIMEDOUT' })).toBe(true)
    expect(isAmbiguousNetworkFailure(new Error('request timeout'))).toBe(true)
    expect(isAmbiguousNetworkFailure(new Error('Network Error'))).toBe(true)
    expect(isAmbiguousNetworkFailure(new Error('ordinary failure'))).toBe(false)
  })

  it('distinguishes committed and still-pending mutations with and without an expected thread', async () => {
    mockedBootstrap
      .mockResolvedValueOnce(bootstrapState(12, null))
      .mockResolvedValueOnce(bootstrapState(12, 7))
      .mockResolvedValueOnce(bootstrapState(12, 7))
      .mockResolvedValueOnce(bootstrapState(12, 9))
      .mockResolvedValueOnce({
        ...bootstrapState(12, null),
        pending_thread_id: 'invalid' as unknown as number,
      })

    await expect(reconcileAmbiguousRollMutation()).resolves.toBe(true)
    await expect(reconcileAmbiguousRollMutation()).resolves.toBe(false)
    await expect(reconcileAmbiguousRollMutation(7)).resolves.toBe(false)
    await expect(reconcileAmbiguousRollMutation(7)).resolves.toBe(true)
    await expect(reconcileAmbiguousRollMutation()).resolves.toBe(true)
    expect(mockedBootstrap).toHaveBeenCalledTimes(5)
  })

  it('does not publish when the browser CustomEvent API is unavailable', () => {
    const reconciled = vi.fn()
    window.addEventListener(ROLL_BOOTSTRAP_RECONCILED_EVENT, reconciled)
    vi.stubGlobal('CustomEvent', undefined)

    try {
      publishRollBootstrap(bootstrapState(8, null))
      expect(reconciled).not.toHaveBeenCalled()
    } finally {
      vi.unstubAllGlobals()
      window.removeEventListener(ROLL_BOOTSTRAP_RECONCILED_EVENT, reconciled)
    }
  })

  it('replaces mounted Roll bootstrap state when a mutation publishes reconciliation', async () => {
    const initial = bootstrapState(6, 7)
    const reconciled = bootstrapState(8, null)
    mockedBootstrap.mockResolvedValue(initial)

    const { result } = renderHook(() => useRollBootstrap(), {
      wrapper: ({ children }: { children: React.ReactNode }) => (
        <ToastProvider>{children}</ToastProvider>
      ),
    })

    await waitFor(() => expect(result.current.data).toBe(initial))

    act(() => {
      window.dispatchEvent(new Event(ROLL_BOOTSTRAP_RECONCILED_EVENT))
    })
    expect(result.current.data).toBe(initial)

    act(() => {
      publishRollBootstrap(reconciled)
    })

    expect(result.current.data).toBe(reconciled)
    expect(result.current.data?.current_die).toBe(8)
    expect(result.current.data?.pending_thread_id).toBeNull()
    expect(result.current.isPending).toBe(false)
    expect(result.current.isError).toBe(false)
    expect(result.current.error).toBeNull()
  })
})
