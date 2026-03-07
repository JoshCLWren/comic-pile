import { act, renderHook } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { useRate } from '../hooks/useRate'
import { rateApi } from '../services/api'

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

  await act(async () => {
    await result.current.mutate({ rating: 4 })
  })

  expect(mockedRateApi.rate).toHaveBeenCalledWith({ rating: 4 })
})
