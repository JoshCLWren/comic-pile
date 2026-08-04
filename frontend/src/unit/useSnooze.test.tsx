import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useSnooze, useUnsnooze } from '../hooks/useSnooze'
import { ROLL_BOOTSTRAP_RECONCILED_EVENT } from '../hooks/rollMutationReconciliation'
import type { RollBootstrapResponse } from '../types/rollBootstrap'

const snoozeApi = vi.hoisted(() => ({ snooze: vi.fn(), unsnooze: vi.fn() }))
const rollBootstrapApi = vi.hoisted(() => ({ get: vi.fn() }))

vi.mock('../services/api', () => ({ snoozeApi }))
vi.mock('../services/rollBootstrapApi', () => ({ rollBootstrapApi }))

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
      expect(snooze.result.current.isError).toBe(false)

      const unsnooze = renderHook(() => useUnsnooze())
      await act(async () => await unsnooze.result.current.mutate(7))
      expect(snoozeApi.unsnooze).toHaveBeenCalledWith(7)
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
  })
})
