import { act, renderHook } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { useRate } from '../hooks/useRate'
import { rateApi } from '../services/api'
import type { RatePayload, Thread } from '../types'

vi.mock('../services/api', () => ({
  rateApi: {
    rate: vi.fn(),
  },
}))

const mockedRateApi = vi.mocked(rateApi)

const ratedThread: Thread = {
  id: 1,
  title: 'Rated thread',
  format: 'issue',
  issues_remaining: 9,
  total_issues: 10,
  next_unread_issue_id: 2,
  next_unread_issue_number: '2',
  reading_progress: '10.00',
  queue_position: 1,
  status: 'active',
  is_blocked: false,
  blocking_reasons: [],
  collection_id: null,
  notes: null,
  last_activity_at: '2026-08-03T01:00:00Z',
  created_at: '2026-08-01T00:00:00Z',
}

beforeEach(() => {
  mockedRateApi.rate.mockResolvedValue(ratedThread)
})

it('submits ratings and returns the authoritative updated thread', async () => {
  const { result } = renderHook(() => useRate())
  const payload: RatePayload = { thread_id: 1, rating: 4 }
  let response: Thread | undefined

  await act(async () => {
    response = await result.current.mutate(payload)
  })

  expect(mockedRateApi.rate).toHaveBeenCalledWith(payload)
  expect(response).toEqual(ratedThread)
})
