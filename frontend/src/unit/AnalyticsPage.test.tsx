import { render, screen } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import AnalyticsPage from '../pages/AnalyticsPage'
import { useAnalytics } from '../hooks/useAnalytics'

vi.mock('../hooks/useAnalytics', () => ({ useAnalytics: vi.fn() }))

beforeEach(() => {
  useAnalytics.mockReturnValue({
    data: {
      total_threads: 12,
      active_threads: 8,
      completed_threads: 4,
      completion_rate: 80,
      average_session_hours: 2.5,
      event_stats: { roll: 25, rate: 15, undo: 3, snooze: 5 },
      recent_sessions: [],
      top_rated_threads: [],
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
