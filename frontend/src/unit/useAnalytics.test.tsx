import { renderHook, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { useAnalytics } from '../hooks/useAnalytics'
import type { AnalyticsTasksApi } from '../hooks/useAnalytics'
import type { AnalyticsMetrics } from '../types'

function makeMetrics(): AnalyticsMetrics {
  return {
    total_threads: 5,
    active_threads: 2,
    completed_threads: 3,
    completion_rate: 0.6,
    average_session_hours: 1.5,
    recent_sessions: [],
    event_stats: {},
    top_rated_threads: [],
  }
}

const getMetrics = vi.fn<() => Promise<AnalyticsMetrics>>()
const api: AnalyticsTasksApi = { getMetrics }

beforeEach(() => {
  getMetrics.mockResolvedValue(makeMetrics())
})

it('loads analytics metrics', async () => {
  const { result } = renderHook(() => useAnalytics(api))

  await waitFor(() => expect(result.current.data).toEqual(makeMetrics()))
  expect(getMetrics).toHaveBeenCalled()
})