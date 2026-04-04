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
