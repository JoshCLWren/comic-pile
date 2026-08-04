import { act, renderHook } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { useRate } from '../hooks/useRate'
import { rateApi } from '../services/api'
import { rollBootstrapApi } from '../services/rollBootstrapApi'
import type { RatePayload } from '../types'

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

beforeEach(() => {
  vi.clearAllMocks()
  mockedRateApi.rate.mockResolvedValue(undefined as never)
  mockedRollBootstrapApi.get.mockResolvedValue({
    session_id: 1,
    user_id: 1,
    current_die: 8,
    manual_die: null,
    pending_thread_id: 1,
    last_rolled_result: 1,
    active_thread: null,
    roll_pool: [],
    blocked_threads: [],
    snoozed_threads: [],
    stale_thread: null,
    stale_thread_count: 0,
  })
})

it('submits ratings', async () => {
  const { result } = renderHook(() => useRate())
  const payload: RatePayload = { thread_id: 1, rating: 4 }

  await act(async () => {
    await result.current.mutate(payload)
  })

  expect(mockedRateApi.rate).toHaveBeenCalledWith(payload)
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

  expect(result.current.isPending).toBe(false)
  expect(result.current.isError).toBe(false)
})

it('reconciles a timeout that committed and prevents a second rating request', async () => {
  const timeout = Object.assign(new Error('timeout of 10000ms exceeded'), {
    code: 'ECONNABORTED',
  })
  mockedRateApi.rate.mockRejectedValue(timeout)
  mockedRollBootstrapApi.get.mockResolvedValue({
    session_id: 1,
    user_id: 1,
    current_die: 10,
    manual_die: null,
    pending_thread_id: null,
    last_rolled_result: null,
    active_thread: null,
    roll_pool: [],
    blocked_threads: [],
    snoozed_threads: [],
    stale_thread: null,
    stale_thread_count: 0,
  })
  const reload = vi.fn()
  vi.stubGlobal('location', { reload })

  const { result } = renderHook(() => useRate())
  const payload: RatePayload = { thread_id: 1, rating: 3 }
  let firstRequest: Promise<unknown> | undefined
  let secondRequest: Promise<unknown> | undefined

  await act(async () => {
    firstRequest = result.current.mutate(payload)
    secondRequest = result.current.mutate(payload)
    await Promise.all([firstRequest, secondRequest])
  })

  expect(mockedRateApi.rate).toHaveBeenCalledTimes(1)
  expect(mockedRollBootstrapApi.get).toHaveBeenCalledTimes(1)
  expect(reload).toHaveBeenCalledTimes(1)
  expect(result.current.isError).toBe(false)
  expect(result.current.isPending).toBe(false)

  vi.unstubAllGlobals()
})

it('surfaces a timeout when authoritative state still has the same pending thread', async () => {
  const timeout = Object.assign(new Error('timeout of 10000ms exceeded'), {
    code: 'ECONNABORTED',
  })
  mockedRateApi.rate.mockRejectedValue(timeout)

  const { result } = renderHook(() => useRate())
  const payload: RatePayload = { thread_id: 1, rating: 3 }

  await act(async () => {
    await expect(result.current.mutate(payload)).rejects.toBe(timeout)
  })

  expect(mockedRollBootstrapApi.get).toHaveBeenCalledTimes(1)
  expect(result.current.isError).toBe(true)
  expect(result.current.isPending).toBe(false)
})
