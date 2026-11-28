import { type ReactNode } from 'react'
import { act, renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useSnooze } from '../hooks/useSnooze'
import { ROLL_STATE_RECONCILED_EVENT } from '../hooks/rollMutationReconciliation'
import type { RollState } from '../types/rollState'

let client: QueryClient

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

function makeSnoozeApi() {
  return { snooze: vi.fn() }
}

function makeProtectedApi() {
  return { rate: vi.fn(), snooze: vi.fn(), skip: vi.fn(), rollState: vi.fn() }
}

function makeBootstrapApi() {
  return { get: vi.fn(), switchPrerequisite: vi.fn() }
}

const snoozeApi = makeSnoozeApi()
const protectedRollMutationApi = makeProtectedApi()
const rollStateApi = makeBootstrapApi()
const deps = { snoozeApi, protectedApi: protectedRollMutationApi, stateApi: rollStateApi }

function renderSnooze() {
  return renderHook(() => useSnooze(deps), { wrapper })
}

const bootstrapState = (pendingThreadId: number | null): RollState => ({
  pending_thread_id: pendingThreadId,
  last_rolled_result: pendingThreadId === null ? null : 1,
  active_thread: null,
  roll_pool: [],
  snoozed_threads: pendingThreadId === null
    ? [{ id: 7, title: 'Doom Patrol', format: 'series' }]
    : [],
  snoozed_count: pendingThreadId === null ? 1 : 0,
})

describe('snooze hooks', () => {
  beforeEach(() => {
    client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    vi.clearAllMocks()
    protectedRollMutationApi.snooze.mockResolvedValue(undefined)
    rollStateApi.get.mockResolvedValue(bootstrapState(null))
  })

  it('snoozes and publishes authoritative Roll state', async () => {
    const reconciled = vi.fn()
    window.addEventListener(ROLL_STATE_RECONCILED_EVENT, reconciled)

    try {
      const snooze = renderSnooze()
      await act(async () => await snooze.result.current.mutate(7))

      expect(protectedRollMutationApi.snooze).toHaveBeenCalledTimes(1)
      expect(rollStateApi.get).toHaveBeenCalledTimes(1)
      expect(reconciled).toHaveBeenCalledTimes(1)
      expect(snooze.result.current.isError).toBe(false)
    } finally {
      window.removeEventListener(ROLL_STATE_RECONCILED_EVENT, reconciled)
    }
  })

  it('shares one in-flight snooze request across repeated submissions', async () => {
    let resolveRequest: (() => void) | undefined
    protectedRollMutationApi.snooze.mockReturnValue(new Promise((resolve) => {
      resolveRequest = () => resolve(undefined)
    }))

    const snooze = renderSnooze()
    let firstRequest: Promise<unknown> | undefined
    let secondRequest: Promise<unknown> | undefined

    act(() => {
      firstRequest = snooze.result.current.mutate(7)
      secondRequest = snooze.result.current.mutate(7)
    })

    expect(protectedRollMutationApi.snooze).toHaveBeenCalledTimes(1)
    expect(snooze.result.current.isPending).toBe(true)

    await act(async () => {
      resolveRequest?.()
      await Promise.all([firstRequest, secondRequest])
    })

    expect(rollStateApi.get).toHaveBeenCalledTimes(1)
    expect(snooze.result.current.isPending).toBe(false)
    expect(snooze.result.current.isError).toBe(false)
  })

  it('retries a failed post-snooze refresh once and publishes authoritative state', async () => {
    const refreshFailure = new Error('bootstrap unavailable')
    rollStateApi.get
      .mockRejectedValueOnce(refreshFailure)
      .mockResolvedValueOnce(bootstrapState(null))
    const reconciled = vi.fn()
    window.addEventListener(ROLL_STATE_RECONCILED_EVENT, reconciled)

    try {
      const snooze = renderSnooze()
      await act(async () => await snooze.result.current.mutate(7))

      expect(protectedRollMutationApi.snooze).toHaveBeenCalledTimes(1)
      expect(rollStateApi.get).toHaveBeenCalledTimes(2)
      expect(reconciled).toHaveBeenCalledTimes(1)
      expect(snooze.result.current.isError).toBe(false)
      expect(snooze.result.current.hasRefreshError).toBe(false)
    } finally {
      window.removeEventListener(ROLL_STATE_RECONCILED_EVENT, reconciled)
    }
  })

  it('exposes exhausted refresh recovery and retries without repeating the snooze', async () => {
    const refreshFailure = new Error('bootstrap unavailable')
    rollStateApi.get.mockRejectedValue(refreshFailure)
    const snooze = renderSnooze()

    await act(async () => await snooze.result.current.mutate(7))

    expect(protectedRollMutationApi.snooze).toHaveBeenCalledTimes(1)
    expect(rollStateApi.get).toHaveBeenCalledTimes(2)
    expect(snooze.result.current.isError).toBe(false)
    expect(snooze.result.current.hasRefreshError).toBe(true)
    expect(snooze.result.current.refreshError).toBe(refreshFailure)

    rollStateApi.get.mockResolvedValue(bootstrapState(null))
    await act(async () => {
      await expect(snooze.result.current.retryRefresh()).resolves.toBe(true)
    })

    expect(protectedRollMutationApi.snooze).toHaveBeenCalledTimes(1)
    expect(rollStateApi.get).toHaveBeenCalledTimes(3)
    expect(snooze.result.current.hasRefreshError).toBe(false)
    expect(snooze.result.current.isPending).toBe(false)
  })

  it('blocks duplicate snooze submission while an explicit refresh retry is pending', async () => {
    const refreshFailure = new Error('bootstrap unavailable')
    rollStateApi.get.mockRejectedValue(refreshFailure)
    const snooze = renderSnooze()

    await act(async () => await snooze.result.current.mutate(7))

    let resolveRefresh: ((value: RollState) => void) | undefined
    rollStateApi.get.mockReturnValue(new Promise((resolve) => {
      resolveRefresh = resolve
    }))

    let retryRequest: Promise<boolean> | undefined
    let duplicateRequest: Promise<unknown> | undefined
    act(() => {
      retryRequest = snooze.result.current.retryRefresh()
      duplicateRequest = snooze.result.current.mutate(7)
    })

    expect(protectedRollMutationApi.snooze).toHaveBeenCalledTimes(1)
    expect(snooze.result.current.isPending).toBe(true)

    await act(async () => {
      resolveRefresh?.(bootstrapState(null))
      await Promise.all([retryRequest, duplicateRequest])
    })

    expect(protectedRollMutationApi.snooze).toHaveBeenCalledTimes(1)
    expect(snooze.result.current.isPending).toBe(false)
    expect(snooze.result.current.hasRefreshError).toBe(false)
  })

  it('reconciles a committed snooze after the delayed response crosses the client timeout', async () => {
    vi.useFakeTimers()
    const timeout = Object.assign(new Error('timeout of 10000ms exceeded'), {
      code: 'ECONNABORTED',
    })
    protectedRollMutationApi.snooze.mockImplementation(() => new Promise((_, reject) => {
      setTimeout(() => reject(timeout), 10_000)
    }))
    rollStateApi.get.mockResolvedValue(bootstrapState(null))

    try {
      const snooze = renderSnooze()
      let request: Promise<unknown> | undefined

      act(() => {
        request = snooze.result.current.mutate(7)
      })

      await act(async () => {
        await vi.advanceTimersByTimeAsync(10_000)
        await request
      })

      expect(protectedRollMutationApi.snooze).toHaveBeenCalledTimes(1)
      expect(rollStateApi.get).toHaveBeenCalledTimes(1)
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
    protectedRollMutationApi.snooze.mockImplementation(() => new Promise((_, reject) => {
      setTimeout(() => reject(timeout), 10_000)
    }))
    rollStateApi.get.mockResolvedValue(bootstrapState(7))

    try {
      const snooze = renderSnooze()
      let request!: Promise<unknown>

      act(() => {
        request = snooze.result.current.mutate(7)
      })

      const rejection = expect(request).rejects.toBe(timeout)
      await act(async () => {
        await vi.advanceTimersByTimeAsync(10_000)
        await rejection
      })

      expect(rollStateApi.get).toHaveBeenCalledTimes(1)
      expect(snooze.result.current.isError).toBe(true)
      expect(snooze.result.current.isPending).toBe(false)
    } finally {
      vi.useRealTimers()
    }
  })

  it('tracks and rethrows ordinary failures', async () => {
    protectedRollMutationApi.snooze.mockRejectedValueOnce(new Error('snooze failed'))
    const snooze = renderSnooze()
    await act(async () => await expect(snooze.result.current.mutate(7)).rejects.toThrow('snooze failed'))
    await waitFor(() => expect(snooze.result.current.isError).toBe(true))

  })

  it('handles "No pending thread to snooze" error like other errors', async () => {
    const error = new Error('No pending thread to snooze. Please roll the dice first.')
    protectedRollMutationApi.snooze.mockRejectedValueOnce(error)

    const snooze = renderSnooze()
    await act(async () => {
      await expect(snooze.result.current.mutate(7)).rejects.toThrow('No pending thread to snooze')
    })

    expect(protectedRollMutationApi.snooze).toHaveBeenCalledTimes(1)
    expect(rollStateApi.get).not.toHaveBeenCalled()
    expect(snooze.result.current.isError).toBe(true)
  })
})
