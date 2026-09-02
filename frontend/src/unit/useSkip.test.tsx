import { type ReactNode } from 'react'
import { act, renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useSkip, useUnskip } from '../hooks/useSkip'
import { ROLL_BOOTSTRAP_RECONCILED_EVENT } from '../hooks/rollMutationReconciliation'
import type { RollBootstrapResponse } from '../types/rollBootstrap'

let client: QueryClient

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

const skipApi = vi.hoisted(() => ({ skip: vi.fn(), unskip: vi.fn() }))
const protectedRollMutationApi = vi.hoisted(() => ({
  rate: vi.fn(),
  snooze: vi.fn(),
  skip: vi.fn(),
  bootstrap: vi.fn(),
}))
const rollBootstrapApi = vi.hoisted(() => ({ get: vi.fn() }))
const invalidateCurrentSessionAfterSnooze = vi.hoisted(() => vi.fn())

vi.mock('../services/api', () => ({ skipApi }))
vi.mock('../services/protectedRollMutationApi', () => ({ protectedRollMutationApi }))
vi.mock('../services/rollBootstrapApi', () => ({ rollBootstrapApi }))
vi.mock('../query/cacheEffects', () => ({ invalidateCurrentSessionAfterSnooze }))

const bootstrapState = (
  pendingThreadId: number | null,
  currentDie = 12,
): RollBootstrapResponse => ({
  session_id: 1,
  user_id: 1,
  current_die: currentDie as RollBootstrapResponse['current_die'],
  manual_die: null,
  pending_thread_id: pendingThreadId,
  last_rolled_result: pendingThreadId === null ? null : 1,
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
  blocked_count: 0,
  blocked_threads: [],
  skipped_thread_ids: pendingThreadId === null ? [7] : [],
  skipped_threads: pendingThreadId === null ? [{ id: 7, title: 'Saga', format: 'Comic' }] : [],
  stale_thread_count: 0,
  stale_thread: null,
})

describe('skip hooks', () => {
  beforeEach(() => {
    client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    vi.clearAllMocks()
    invalidateCurrentSessionAfterSnooze.mockReset()
    protectedRollMutationApi.skip.mockResolvedValue(undefined)
    skipApi.unskip.mockResolvedValue(undefined)
    rollBootstrapApi.get.mockResolvedValue(bootstrapState(null))
  })

  it('skips, publishes authoritative Roll state, and unskips successfully', async () => {
    const reconciled = vi.fn()
    window.addEventListener(ROLL_BOOTSTRAP_RECONCILED_EVENT, reconciled)

    try {
      const skip = renderHook(() => useSkip(), { wrapper })
      await act(async () => await skip.result.current.mutate(7))

      expect(protectedRollMutationApi.skip).toHaveBeenCalledTimes(1)
      expect(rollBootstrapApi.get).toHaveBeenCalledTimes(1)
      expect(reconciled).toHaveBeenCalledTimes(1)
      expect(invalidateCurrentSessionAfterSnooze).toHaveBeenCalledWith(client)
      expect(skip.result.current.isError).toBe(false)

      const unskip = renderHook(() => useUnskip(), { wrapper })
      await act(async () => await unskip.result.current.mutate(7))
      expect(skipApi.unskip).toHaveBeenCalledWith(7)
      expect(invalidateCurrentSessionAfterSnooze).toHaveBeenCalledTimes(2)
      expect(invalidateCurrentSessionAfterSnooze).toHaveBeenLastCalledWith(client)
    } finally {
      window.removeEventListener(ROLL_BOOTSTRAP_RECONCILED_EVENT, reconciled)
    }
  })

  it('shares one in-flight skip request across repeated submissions', async () => {
    let resolveRequest: (() => void) | undefined
    protectedRollMutationApi.skip.mockReturnValue(new Promise((resolve) => {
      resolveRequest = () => resolve(undefined)
    }))

    const skip = renderHook(() => useSkip(), { wrapper })
    let firstRequest: Promise<unknown> | undefined
    let secondRequest: Promise<unknown> | undefined

    act(() => {
      firstRequest = skip.result.current.mutate(7)
      secondRequest = skip.result.current.mutate(7)
    })

    expect(protectedRollMutationApi.skip).toHaveBeenCalledTimes(1)
    expect(skip.result.current.isPending).toBe(true)

    await act(async () => {
      resolveRequest?.()
      await Promise.all([firstRequest, secondRequest])
    })

    expect(rollBootstrapApi.get).toHaveBeenCalledTimes(1)
    expect(skip.result.current.isPending).toBe(false)
    expect(skip.result.current.isError).toBe(false)
  })

  it('retries a failed post-skip refresh once and publishes authoritative state', async () => {
    const refreshFailure = new Error('bootstrap unavailable')
    rollBootstrapApi.get
      .mockRejectedValueOnce(refreshFailure)
      .mockResolvedValueOnce(bootstrapState(null, 20))
    const reconciled = vi.fn()
    window.addEventListener(ROLL_BOOTSTRAP_RECONCILED_EVENT, reconciled)

    try {
      const skip = renderHook(() => useSkip(), { wrapper })
      await act(async () => await skip.result.current.mutate(7))

      expect(protectedRollMutationApi.skip).toHaveBeenCalledTimes(1)
      expect(rollBootstrapApi.get).toHaveBeenCalledTimes(2)
      expect(reconciled).toHaveBeenCalledTimes(1)
      expect(skip.result.current.isError).toBe(false)
      expect(skip.result.current.hasRefreshError).toBe(false)
    } finally {
      window.removeEventListener(ROLL_BOOTSTRAP_RECONCILED_EVENT, reconciled)
    }
  })

  it('exposes exhausted refresh recovery and retries without repeating the skip', async () => {
    const refreshFailure = new Error('bootstrap unavailable')
    rollBootstrapApi.get.mockRejectedValue(refreshFailure)
    const skip = renderHook(() => useSkip(), { wrapper })

    await act(async () => await skip.result.current.mutate(7))

    expect(protectedRollMutationApi.skip).toHaveBeenCalledTimes(1)
    expect(rollBootstrapApi.get).toHaveBeenCalledTimes(2)
    expect(skip.result.current.isError).toBe(false)
    expect(skip.result.current.hasRefreshError).toBe(true)
    expect(skip.result.current.refreshError).toBe(refreshFailure)

    rollBootstrapApi.get.mockResolvedValue(bootstrapState(null, 20))
    await act(async () => {
      await expect(skip.result.current.retryRefresh()).resolves.toBe(true)
    })

    expect(protectedRollMutationApi.skip).toHaveBeenCalledTimes(1)
    expect(rollBootstrapApi.get).toHaveBeenCalledTimes(3)
    expect(skip.result.current.hasRefreshError).toBe(false)
    expect(skip.result.current.isPending).toBe(false)
  })

  it('blocks duplicate skip submission while an explicit refresh retry is pending', async () => {
    const refreshFailure = new Error('bootstrap unavailable')
    rollBootstrapApi.get.mockRejectedValue(refreshFailure)
    const skip = renderHook(() => useSkip(), { wrapper })

    await act(async () => await skip.result.current.mutate(7))

    let resolveRefresh: ((value: RollBootstrapResponse) => void) | undefined
    rollBootstrapApi.get.mockReturnValue(new Promise((resolve) => {
      resolveRefresh = resolve
    }))

    let retryRequest: Promise<boolean> | undefined
    let duplicateRequest: Promise<unknown> | undefined
    act(() => {
      retryRequest = skip.result.current.retryRefresh()
      duplicateRequest = skip.result.current.mutate(7)
    })

    expect(protectedRollMutationApi.skip).toHaveBeenCalledTimes(1)
    expect(skip.result.current.isPending).toBe(true)

    await act(async () => {
      resolveRefresh?.(bootstrapState(null, 20))
      await Promise.all([retryRequest, duplicateRequest])
    })

    expect(protectedRollMutationApi.skip).toHaveBeenCalledTimes(1)
    expect(skip.result.current.isPending).toBe(false)
    expect(skip.result.current.hasRefreshError).toBe(false)
  })

  it('reconciles a committed skip after the delayed response crosses the client timeout', async () => {
    vi.useFakeTimers()
    const timeout = Object.assign(new Error('timeout of 10000ms exceeded'), {
      code: 'ECONNABORTED',
    })
    protectedRollMutationApi.skip.mockImplementation(() => new Promise((_, reject) => {
      setTimeout(() => reject(timeout), 10_000)
    }))
    rollBootstrapApi.get.mockResolvedValue(bootstrapState(null, 20))

    try {
      const skip = renderHook(() => useSkip(), { wrapper })
      let request: Promise<unknown> | undefined

      act(() => {
        request = skip.result.current.mutate(7)
      })

      await act(async () => {
        await vi.advanceTimersByTimeAsync(10_000)
        await request
      })

      expect(protectedRollMutationApi.skip).toHaveBeenCalledTimes(1)
      expect(rollBootstrapApi.get).toHaveBeenCalledTimes(1)
      expect(skip.result.current.isError).toBe(false)
      expect(skip.result.current.isPending).toBe(false)
    } finally {
      vi.useRealTimers()
    }
  })

  it('surfaces a delayed timeout when the same thread is still pending', async () => {
    vi.useFakeTimers()
    const timeout = Object.assign(new Error('timeout of 10000ms exceeded'), {
      code: 'ECONNABORTED',
    })
    protectedRollMutationApi.skip.mockImplementation(() => new Promise((_, reject) => {
      setTimeout(() => reject(timeout), 10_000)
    }))
    rollBootstrapApi.get.mockResolvedValue(bootstrapState(7, 10))

    try {
      const skip = renderHook(() => useSkip(), { wrapper })
      let request!: Promise<unknown>

      act(() => {
        request = skip.result.current.mutate(7)
      })

      const rejection = expect(request).rejects.toBe(timeout)
      await act(async () => {
        await vi.advanceTimersByTimeAsync(10_000)
        await rejection
      })

      expect(rollBootstrapApi.get).toHaveBeenCalledTimes(1)
      expect(skip.result.current.isError).toBe(true)
      expect(skip.result.current.isPending).toBe(false)
    } finally {
      vi.useRealTimers()
    }
  })

  it('recovers skip after authentication failure and retries', async () => {
    const authError = Object.assign(new Error('Not authenticated'), {
      response: { status: 403, data: { detail: 'Not authenticated' } },
    })
    protectedRollMutationApi.skip.mockRejectedValueOnce(authError)
    protectedRollMutationApi.skip.mockResolvedValueOnce(undefined)
    protectedRollMutationApi.bootstrap.mockResolvedValue(bootstrapState(7, 12))

    const skipHook = renderHook(() => useSkip(), { wrapper })
    await act(async () => await skipHook.result.current.mutate(7))

    expect(protectedRollMutationApi.skip).toHaveBeenCalledTimes(2)
    expect(skipHook.result.current.isError).toBe(false)
  })

  it('reconciles ambiguous skip after network timeout when thread is no longer pending', async () => {
    const timeoutError = Object.assign(new Error('timeout'), { code: 'ECONNABORTED' })
    protectedRollMutationApi.skip.mockRejectedValueOnce(timeoutError)
    rollBootstrapApi.get.mockResolvedValue(bootstrapState(null, 20))

    const skipHook = renderHook(() => useSkip(), { wrapper })
    await act(async () => await skipHook.result.current.mutate(7))

    expect(protectedRollMutationApi.skip).toHaveBeenCalledTimes(1)
    expect(skipHook.result.current.isError).toBe(false)
  })

  it('tracks and rethrows ordinary failures', async () => {
    protectedRollMutationApi.skip.mockRejectedValueOnce(new Error('skip failed'))
    const skip = renderHook(() => useSkip(), { wrapper })
    await act(async () => await expect(skip.result.current.mutate(7)).rejects.toThrow('skip failed'))
    await waitFor(() => expect(skip.result.current.isError).toBe(true))

    skipApi.unskip.mockRejectedValueOnce(new Error('unskip failed'))
    const unskip = renderHook(() => useUnskip(), { wrapper })
    await act(async () => await expect(unskip.result.current.mutate(7)).rejects.toThrow('unskip failed'))
    await waitFor(() => expect(unskip.result.current.isError).toBe(true))

    expect(invalidateCurrentSessionAfterSnooze).not.toHaveBeenCalled()
  })

  it('logs authentication recovery failure without marking stale skip as error', async () => {
    const authError = Object.assign(new Error('Not authenticated'), {
      response: { status: 403, data: { detail: 'Not authenticated' } },
    })
    const recoveryError = new Error('bootstrap down')
    protectedRollMutationApi.skip.mockRejectedValueOnce(authError)
    protectedRollMutationApi.bootstrap.mockRejectedValueOnce(recoveryError)
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    const skip = renderHook(() => useSkip(), { wrapper })
    await act(async () => await expect(skip.result.current.mutate(7)).rejects.toThrow('Not authenticated'))
    expect(errorSpy).toHaveBeenCalledWith(
      'Failed to recover skip after authentication expiry:',
      expect.any(String),
    )
    errorSpy.mockRestore()
  })

  it('logs ambiguous reconciliation failure and rethrows original network error', async () => {
    const timeoutError = Object.assign(new Error('timeout'), { code: 'ECONNABORTED' })
    const reconcileError = new Error('reconcile down')
    protectedRollMutationApi.skip.mockRejectedValueOnce(timeoutError)
    rollBootstrapApi.get.mockRejectedValueOnce(reconcileError)
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    const skip = renderHook(() => useSkip(), { wrapper })
    await act(async () => await expect(skip.result.current.mutate(7)).rejects.toThrow('timeout'))
    expect(errorSpy).toHaveBeenCalledWith(
      'Failed to reconcile ambiguous skip result:',
      expect.any(String),
    )
    errorSpy.mockRestore()
  })
})
