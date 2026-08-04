import { act, renderHook } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { useRate } from '../hooks/useRate'
import { ROLL_BOOTSTRAP_RECONCILED_EVENT } from '../hooks/rollMutationReconciliation'
import { rateApi } from '../services/api'
import { rollBootstrapApi } from '../services/rollBootstrapApi'
import type { RatePayload } from '../types'
import type { RollBootstrapResponse } from '../types/rollBootstrap'

vi.mock('../services/api', () => ({
  rateApi: {
    rate: vi.fn(),
  },
}))

vi.mock('../services/rollBootstrapApi', () => ({
  rollBootstrapApi: {
    get: vi.fn(),
  },
}))

const mockedRateApi = vi.mocked(rateApi)
const mockedRollBootstrapApi = vi.mocked(rollBootstrapApi)

const bootstrapState = (
  pendingThreadId: number | null,
  currentDie: RollBootstrapResponse['current_die'] = 8,
): RollBootstrapResponse => ({
  session_id: 1,
  user_id: 1,
  current_die: currentDie,
  manual_die: null,
  pending_thread_id: pendingThreadId,
  last_rolled_result: pendingThreadId === null ? null : 1,
  active_thread: null,
  roll_pool: [],
  blocked_threads: [],
  blocked_count: 0,
  snoozed_threads: [],
  snoozed_count: 0,
  stale_thread: null,
  stale_thread_count: 0,
})

beforeEach(() => {
  vi.clearAllMocks()
  mockedRateApi.rate.mockResolvedValue(undefined as never)
  mockedRollBootstrapApi.get.mockResolvedValue(bootstrapState(null))
})

it('submits ratings and publishes authoritative Roll state', async () => {
  const reconciled = vi.fn()
  window.addEventListener(ROLL_BOOTSTRAP_RECONCILED_EVENT, reconciled)

  try {
    const { result } = renderHook(() => useRate())
    const payload: RatePayload = { thread_id: 1, rating: 4 }

    await act(async () => {
      await result.current.mutate(payload)
    })

    expect(mockedRateApi.rate).toHaveBeenCalledWith(payload)
    expect(mockedRollBootstrapApi.get).toHaveBeenCalledTimes(1)
    expect(reconciled).toHaveBeenCalledTimes(1)
    expect(result.current.isError).toBe(false)
  } finally {
    window.removeEventListener(ROLL_BOOTSTRAP_RECONCILED_EVENT, reconciled)
  }
})

it('shares one in-flight request across repeated submissions', async () => {
  let resolveRequest: (() => void) | undefined
  mockedRateApi.rate.mockReturnValue(new Promise((resolve) => {
    resolveRequest = () => resolve(undefined as never)
  }))

  const { result } = renderHook(() => useRate())
  const payload: RatePayload = { thread_id: 1, rating: 4 }
  let firstRequest: Promise<unknown> | undefined
  let secondRequest: Promise<unknown> | undefined

  act(() => {
    firstRequest = result.current.mutate(payload)
    secondRequest = result.current.mutate(payload)
  })

  expect(mockedRateApi.rate).toHaveBeenCalledTimes(1)
  expect(result.current.isPending).toBe(true)

  await act(async () => {
    resolveRequest?.()
    await Promise.all([firstRequest, secondRequest])
  })

  expect(mockedRollBootstrapApi.get).toHaveBeenCalledTimes(1)
  expect(result.current.isPending).toBe(false)
  expect(result.current.isError).toBe(false)
})

it('reconciles a committed rating after the delayed response crosses the client timeout', async () => {
  vi.useFakeTimers()
  const timeout = Object.assign(new Error('timeout of 10000ms exceeded'), {
    code: 'ECONNABORTED',
  })
  mockedRateApi.rate.mockImplementation(() => new Promise((_, reject) => {
    setTimeout(() => reject(timeout), 10_000)
  }))
  mockedRollBootstrapApi.get.mockResolvedValue(bootstrapState(null, 10))

  try {
    const { result } = renderHook(() => useRate())
    const payload: RatePayload = { thread_id: 1, rating: 3 }
    let firstRequest: Promise<unknown> | undefined
    let secondRequest: Promise<unknown> | undefined

    act(() => {
      firstRequest = result.current.mutate(payload)
      secondRequest = result.current.mutate(payload)
    })

    expect(mockedRateApi.rate).toHaveBeenCalledTimes(1)
    expect(result.current.isPending).toBe(true)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000)
      await Promise.all([firstRequest, secondRequest])
    })

    expect(mockedRollBootstrapApi.get).toHaveBeenCalledTimes(1)
    expect(result.current.isError).toBe(false)
    expect(result.current.isPending).toBe(false)
  } finally {
    vi.useRealTimers()
  }
})

it('surfaces a delayed timeout when authoritative state still has the same pending thread', async () => {
  vi.useFakeTimers()
  const timeout = Object.assign(new Error('timeout of 10000ms exceeded'), {
    code: 'ECONNABORTED',
  })
  mockedRateApi.rate.mockImplementation(() => new Promise((_, reject) => {
    setTimeout(() => reject(timeout), 10_000)
  }))
  mockedRollBootstrapApi.get.mockResolvedValue(bootstrapState(1))

  try {
    const { result } = renderHook(() => useRate())
    const payload: RatePayload = { thread_id: 1, rating: 3 }
    let request!: Promise<unknown>

    act(() => {
      request = result.current.mutate(payload)
    })

    const rejection = expect(request).rejects.toBe(timeout)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000)
      await rejection
    })

    expect(mockedRollBootstrapApi.get).toHaveBeenCalledTimes(1)
    expect(result.current.isError).toBe(true)
    expect(result.current.isPending).toBe(false)
  } finally {
    vi.useRealTimers()
  }
})
