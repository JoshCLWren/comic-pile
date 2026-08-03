import { act, renderHook } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { useRate } from '../hooks/useRate'
import { applyRatedThreadCache } from '../query/cacheEffects'
import { queryClient } from '../query/queryClient'
import { rateApi } from '../services/api'
import type { RatePayload, Thread } from '../types'

vi.mock('../services/api', () => ({
  rateApi: {
    rate: vi.fn(),
  },
}))

vi.mock('../query/cacheEffects', () => ({
  applyRatedThreadCache: vi.fn(),
}))

const mockedRateApi = vi.mocked(rateApi)
const mockedApplyRatedThreadCache = vi.mocked(applyRatedThreadCache)

beforeEach(() => {
  vi.clearAllMocks()
})

it('applies the authoritative rating response to targeted caches', async () => {
  const thread = { id: 1, rating: 4 } as Thread
  mockedRateApi.rate.mockResolvedValue(thread)
  mockedApplyRatedThreadCache.mockResolvedValue()
  const { result } = renderHook(() => useRate())
  const payload: RatePayload = { thread_id: 1, rating: 4 }

  let response: Thread | undefined
  await act(async () => {
    response = await result.current.mutate(payload)
  })

  expect(mockedRateApi.rate).toHaveBeenCalledWith(payload)
  expect(mockedApplyRatedThreadCache).toHaveBeenCalledWith(queryClient, thread)
  expect(response).toBe(thread)
})
