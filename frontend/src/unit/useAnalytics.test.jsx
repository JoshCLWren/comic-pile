import { renderHook, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { useAnalytics } from '../hooks/useAnalytics'
import { tasksApi } from '../services/api'

vi.mock('../services/api', () => ({
  tasksApi: {
    getMetrics: vi.fn(),
  },
}))

beforeEach(() => {
  tasksApi.getMetrics.mockResolvedValue({ total_tasks: 10 })
})

it('loads analytics metrics', async () => {
  const { result } = renderHook(() => useAnalytics())

  await waitFor(() => expect(result.current.data).toEqual({ total_tasks: 10 }))
  expect(tasksApi.getMetrics).toHaveBeenCalled()
})
