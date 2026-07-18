import { render, screen } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import AnalyticsPage from '../pages/AnalyticsPage'
import { useAnalytics } from '../hooks/useAnalytics'

vi.mock('../hooks/useAnalytics', () => ({ useAnalytics: vi.fn() }))

const mockedUseAnalytics = vi.mocked(useAnalytics) as any

beforeEach(() => {
  mockedUseAnalytics.mockReturnValue({
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

it('renders recent sessions, event variants, and top rated threads', () => {
  mockedUseAnalytics.mockReturnValue({ data: {
    total_threads: 0, active_threads: 0, completed_threads: 0, completion_rate: Number.NaN, average_session_hours: Number.NaN,
    recent_sessions: [{ id: 1, start_die: 6, started_at: '2024-01-01T10:00:00Z', ended_at: '2024-01-01T11:00:00Z' }, { id: 2, start_die: 8, started_at: '2024-01-01T12:00:00Z', ended_at: null }],
    event_stats: { roll: 1, rate: 2, undo: 3, other: 4 },
    top_rated_threads: [{ id: 1, title: 'Saga', rating: 4.5, format: 'Comic' }, { id: 2, title: 'Unknown', rating: Number.NaN, format: '' }],
  }, isLoading: false, error: null })
  render(<AnalyticsPage />)
  expect(screen.getByText('Session #1')).toBeInTheDocument()
  expect(screen.getByText('Active')).toBeInTheDocument()
  expect(screen.getAllByText('N/A').length).toBeGreaterThan(0)
})

it('renders loading and error states', () => {
  mockedUseAnalytics.mockReturnValue({ data: null, isLoading: true, error: null })
  const { rerender } = render(<AnalyticsPage />)
  expect(screen.getByText('Loading analytics...')).toBeInTheDocument()
  mockedUseAnalytics.mockReturnValue({ data: null, isLoading: false, error: new Error('bad') })
  rerender(<AnalyticsPage />)
  expect(screen.getByText('Failed to load analytics data')).toBeInTheDocument()
})
