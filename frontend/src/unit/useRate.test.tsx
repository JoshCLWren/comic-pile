import { act, renderHook } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { useRate } from '../hooks/useRate'
import { rateApi } from '../services/api'
import type { RatePayload } from '../types'

vi.mock('../services/api', () => ({
  rateApi: {
    rate: vi.fn(),
  },
}))

const mockedRateApi = vi.mocked(rateApi)

beforeEach(() => {
  vi.clearAllMocks()
  mockedRateApi.rate.mockResolvedValue(undefined as never)
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
