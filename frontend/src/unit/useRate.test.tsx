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
  const thread: Thread = {
    id: 1,
    title: 'Saga',
    format: 'issue',
    issues_remaining: 3,
    total_issues: 10,
    queue_position: 2,
    status: 'active',
    is_blocked: false,
    blocking_reasons: [],
    created_at: '2026-08-03T00:00:00Z',
  }
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
