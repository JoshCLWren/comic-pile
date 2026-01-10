import { render, screen } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import AnalyticsPage from '../pages/AnalyticsPage'
import { useAnalytics } from '../hooks/useAnalytics'

vi.mock('../hooks/useAnalytics', () => ({ useAnalytics: vi.fn() }))

beforeEach(() => {
  useAnalytics.mockReturnValue({
    data: {
      total_tasks: 12,
      completion_rate: 80,
      ready_to_claim: 4,
      average_completion_time_hours: 2,
      tasks_by_status: { done: 5 },
      tasks_by_priority: { HIGH: 2 },
      tasks_by_type: { bug: 1 },
      stale_tasks_count: 0,
      blocked_tasks_count: 0,
      active_agents: [],
      recent_completions: [],
    },
    isLoading: false,
    error: null,
  })
})

it('renders analytics metrics', () => {
  render(<AnalyticsPage />)

  expect(screen.getByText('Analytics')).toBeInTheDocument()
  expect(screen.getByText('12')).toBeInTheDocument()
  expect(screen.getByText('Completion Rate')).toBeInTheDocument()
})
