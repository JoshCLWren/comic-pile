import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useSnooze, useUnsnooze } from '../hooks/useSnooze'
import { ROLL_BOOTSTRAP_RECONCILED_EVENT } from '../hooks/rollMutationReconciliation'
import { queryClient } from '../query/queryClient'
import type { RollBootstrapResponse } from '../types/rollBootstrap'

const snoozeApi = vi.hoisted(() => ({ snooze: vi.fn(), unsnooze: vi.fn() }))
const rollBootstrapApi = vi.hoisted(() => ({ get: vi.fn() }))
const invalidateCurrentSessionAfterSnooze = vi.hoisted(() => vi.fn())

vi.mock('../services/api', () => ({ snoozeApi }))
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
  active_thread: null,
  roll_pool: [],
  snoozed_threads: pendingThreadId === null
    ? [{ id: 7, title: 'Doom Patrol', format: 'series' }]
    : [],
  snoozed_count: pendingThreadId === null ? 1 : 0,
  blocked_count: 0,
  blocked_threads: [],
  stale_thread_count: 0,
  stale_thread: null,
})

describe('snooze hooks', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    invalidateCurrentSessionAfterSnooze.mockReset()
    snoozeApi.snooze.mockResolvedValue(undefined)
    snoozeApi.unsnooze.mockResolvedValue(undefined)
    rollBootstrapApi.get.mockResolvedValue(bootstrapState(null))
  })

  it('snoozes, publishes authoritative Roll state, and unsnoozes successfully', async () => {
    const reconciled = vi.fn()
    window.addEventListener(ROLL_BOOTSTRAP_RECONCILED_EVENT, reconciled)

    try {
      const snooze = renderHook(() => useSnooze())
      await act(async () => await snooze.result.current.mutate(7))

      expect(snoozeApi.snooze).toHaveBeenCalledTimes(1)
      expect(rollBootstrapApi.get).toHaveBeenCalledTimes(1)
      expect(reconciled).toHaveBeenCalledTimes(1)
      expect(invalidateCurrentSessionAfterSnooze).toHaveBeenCalledWith(queryClient)
      expect(snooze.result.current.isError).toBe(false)

      const unsnooze = renderHook(() => useUnsnooze())
      await act(async () => await unsnooze.result.current.mutate(7))
      expect(snoozeApi.unsnooze).toHaveBeenCalledWith(7)
      expect(invalidateCurrentSessionAfterSnooze).toHaveBeenCalledTimes(2)
      expect(invalidateCurrentSessionAfterSnooze).toHaveBeenLastCalledWith(queryClient)
    } finally {
      window.removeEventListener(ROLL_BOOTSTRAP_RECONCILED_EVENT, reconciled)
    }
  })

  it('shares one in-flight snooze request across repeated submissions', async () => {
    let resolveRequest: (() => void) | undefined
    snoozeApi.snooze.mockReturnValue(new Promise((resolve) => {
      resolveRequest = () => resolve(undefined)
    }))

    const snooze = renderHook(() => useSnooze())
    let firstRequest: Promise<unknown> | undefined
    let secondRequest: Promise<unknown> | undefined

    act(() => {
      firstRequest = snooze.result.current.mutate(7)
      secondRequest = snooze.result.current.mutate(7)
    })

    expect(snoozeApi.snooze).toHaveBeenCalledTimes(1)
    expect(snooze.result.current.isPending).toBe(true)

    await act(async () => {
      resolveRequest?.()
      await Promise.all([firstRequest, secondRequest])
    })

    expect(rollBootstrapApi.get).toHaveBeenCalledTimes(1)
    expect(snooze.result.current.isPending).toBe(false)
    expect(snooze.result.current.isError).toBe(false)
  })

  it('retries a failed post-snooze refresh once and publishes authoritative state', async () => {
    const refreshFailure = new Error('bootstrap unavailable')
    rollBootstrapApi.get
      .mockRejectedValueOnce(refreshFailure)
      .mockResolvedValueOnce(bootstrapState(null, 20))
    const reconciled = vi.fn()
    window.addEventListener(ROLL_BOOTSTRAP_RECONCILED_EVENT, reconciled)

    try {
      const snooze = renderHook(() => useSnooze())
      await act(async () => await snooze.result.current.mutate(7))

      expect(snoozeApi.snooze).toHaveBeenCalledTimes(1)
      expect(rollBootstrapApi.get).toHaveBeenCalledTimes(2)
      expect(reconciled).toHaveBeenCalledTimes(1)
      expect(snooze.result.current.isError).toBe(false)
      expect(snooze.result.current.hasRefreshError).toBe(false)
    } finally {
      window.removeEventListener(ROLL_BOOTSTRAP_RECONCILED_EVENT, reconciled)
    }
  })

  it('exposes exhausted refresh recovery and retries without repeating the snooze', async () => {
    const refreshFailure = new Error('bootstrap unavailable')
    rollBootstrapApi.get.mockRejectedValue(refreshFailure)
    const snooze = renderHook(() => useSnooze())

    await act(async () => await snooze.result.current.mutate(7))

    expect(snoozeApi.snooze).toHaveBeenCalledTimes(1)
    expect(rollBootstrapApi.get).toHaveBeenCalledTimes(2)
    expect(snooze.result.current.isError).toBe(false)
    expect(snooze.result.current.hasRefreshError).toBe(true)
    expect(snooze.result.current.refreshError).toBe(refreshFailure)

    rollBootstrapApi.get.mockResolvedValue(bootstrapState(null, 20))
    await act(async () => {
      await expect(snooze.result.current.retryRefresh()).resolves.toBe(true)
    })

    expect(snoozeApi.snooze).toHaveBeenCalledTimes(1)
    expect(rollBootstrapApi.get).toHaveBeenCalledTimes(3)
    expect(snooze.result.current.hasRefreshError).toBe(false)
    expect(snooze.result.current.isPending).toBe(false)
  })

  it('blocks duplicate snooze submission while an explicit refresh retry is pending', async () => {
    const refreshFailure = new Error('bootstrap unavailable')
    rollBootstrapApi.get.mockRejectedValue(refreshFailure)
    const snooze = renderHook(() => useSnooze())

    await act(async () => await snooze.result.current.mutate(7))

    let resolveRefresh: ((value: RollBootstrapResponse) => void) | undefined
    rollBootstrapApi.get.mockReturnValue(new Promise((resolve) => {
      resolveRefresh = resolve
    }))

    let retryRequest: Promise<boolean> | undefined
    let duplicateRequest: Promise<unknown> | undefined
    act(() => {
      retryRequest = snooze.result.current.retryRefresh()
      duplicateRequest = snooze.result.current.mutate(7)
    })

    expect(snoozeApi.snooze).toHaveBeenCalledTimes(1)
    expect(snooze.result.current.isPending).toBe(true)

    await act(async () => {
      resolveRefresh?.(bootstrapState(null, 20))
      await Promise.all([retryRequest, duplicateRequest])
    })

    expect(snoozeApi.snooze).toHaveBeenCalledTimes(1)
    expect(snooze.result.current.isPending).toBe(false)
    expect(snooze.result.current.hasRefreshError).toBe(false)
  })

  it('reconciles a committed snooze after the delayed response crosses the client timeout', async () => {
    vi.useFakeTimers()
    const timeout = Object.assign(new Error('timeout of 10000ms exceeded'), {
      code: 'ECONNABORTED',
    })
    snoozeApi.snooze.mockImplementation(() => new Promise((_, reject) => {
      setTimeout(() => reject(timeout), 10_000)
    }))
    rollBootstrapApi.get.mockResolvedValue(bootstrapState(null, 20))

    try {
      const snooze = renderHook(() => useSnooze())
      let request: Promise<unknown> | undefined

      act(() => {
        request = snooze.result.current.mutate(7)
      })

      await act(async () => {
        await vi.advanceTimersByTimeAsync(10_000)
        await request
      })

      expect(snoozeApi.snooze).toHaveBeenCalledTimes(1)
      expect(rollBootstrapApi.get).toHaveBeenCalledTimes(1)
      expect(snooze.result.current.isError).toBe(false)
      expect(snooze.result.current.isPending).toBe(false)
    } finally {
      vi.useRealTimers()
    }
  })

  it('surfaces a delayed timeout when the same thread is still pending', async () => {
    vi.useFakeTimers()
    const timeout = Object.assign(new Error('timeout of 10000ms exceeded'), {
      code: 'ECONNABORTED',
    })
    snoozeApi.snooze.mockImplementation(() => new Promise((_, reject) => {
      setTimeout(() => reject(timeout), 10_000)
    }))
    rollBootstrapApi.get.mockResolvedValue(bootstrapState(7, 10))

    try {
      const snooze = renderHook(() => useSnooze())
      let request!: Promise<unknown>

      act(() => {
        request = snooze.result.current.mutate(7)
      })

      const rejection = expect(request).rejects.toBe(timeout)
      await act(async () => {
        await vi.advanceTimersByTimeAsync(10_000)
        await rejection
      })

      expect(rollBootstrapApi.get).toHaveBeenCalledTimes(1)
      expect(snooze.result.current.isError).toBe(true)
      expect(snooze.result.current.isPending).toBe(false)
    } finally {
      vi.useRealTimers()
    }
  })

  it('tracks and rethrows ordinary failures', async () => {
    snoozeApi.snooze.mockRejectedValueOnce(new Error('snooze failed'))
    const snooze = renderHook(() => useSnooze())
    await act(async () => await expect(snooze.result.current.mutate(7)).rejects.toThrow('snooze failed'))
    await waitFor(() => expect(snooze.result.current.isError).toBe(true))

    snoozeApi.unsnooze.mockRejectedValueOnce(new Error('unsnooze failed'))
    const unsnooze = renderHook(() => useUnsnooze())
    await act(async () => await expect(unsnooze.result.current.mutate(7)).rejects.toThrow('unsnooze failed'))
    await waitFor(() => expect(unsnooze.result.current.isError).toBe(true))

    expect(invalidateCurrentSessionAfterSnooze).not.toHaveBeenCalled()
  })
})
