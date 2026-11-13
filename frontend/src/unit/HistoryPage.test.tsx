import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
import HistoryPage from '../pages/HistoryPage'
import { useActivity } from '../hooks/useActivity'
import type { ActivityEvent } from '../services/api-activity'

vi.mock('../hooks/useActivity', () => ({ useActivity: vi.fn() }))
const mockedUseActivity = vi.mocked(useActivity)
const loadMore = vi.fn()
const refetch = vi.fn()

function event(event_id: number, action_display: string, overrides: Partial<ActivityEvent> = {}): ActivityEvent {
  return {
    event_id,
    event_type: 'roll',
    timestamp: '2026-11-08T15:42:35.028Z',
    die_before: 6,
    die_after: null,
    rating: null,
    thread_id: 3153,
    thread_title: 'First Series',
    issue_id: 1121330,
    issue_number: '1',
    action_display,
    ...overrides,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  mockedUseActivity.mockReturnValue({
    events: [], isPending: false, isRetrying: false, isError: false, error: null,
    isLoadingMore: false, hasMore: false, loadMore, refetch,
  })
})

it('shows a distinct empty state and refresh action', () => {
  render(<MemoryRouter><HistoryPage /></MemoryRouter>)
  expect(screen.getByText('No activity yet')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Refresh' }))
  expect(refetch).toHaveBeenCalledOnce()
})

it('shows the causal die sequence, one rating, and an owned series link', () => {
  mockedUseActivity.mockReturnValue({
    events: [
      event(7, 'Rated Third Series #2 ⭐4.5', { event_type: 'rate', rating: 4.5, die_before: 10, die_after: 8, thread_id: 8417, thread_title: 'Third Series', issue_id: 52329, issue_number: '2' }),
      event(4, 'Snoozed Second Series (d8 → d10)', { event_type: 'snooze', die_before: 8, die_after: 10, thread_id: 3469, thread_title: 'Second Series', issue_id: null, issue_number: null }),
      event(5, 'Rolled Third Series #2', { die_before: 10, thread_id: 8417, thread_title: 'Third Series', issue_id: 52329, issue_number: '2' }),
      event(2, 'Snoozed First Series (d6 → d8)', { event_type: 'snooze', die_after: 8, issue_id: null, issue_number: null }),
      event(3, 'Rolled Second Series #2', { die_before: 8, thread_id: 3469, thread_title: 'Second Series', issue_id: 25301, issue_number: '2' }),
      event(1, 'Rolled First Series #1'),
    ],
    isPending: false, isRetrying: false, isError: false, error: null,
    isLoadingMore: false, hasMore: true, loadMore, refetch,
  })
  render(<MemoryRouter><HistoryPage /></MemoryRouter>)
  const rows = screen.getAllByRole('listitem')
  expect(rows).toHaveLength(6)
  expect(rows.map((row) => row.querySelector('p')?.textContent)).toEqual([
    'Rated Third Series #2 ⭐4.5',
    'Snoozed Second Series (d8 → d10)',
    'Rolled Third Series #2',
    'Snoozed First Series (d6 → d8)',
    'Rolled Second Series #2',
    'Rolled First Series #1',
  ])
  expect(screen.getByRole('link', { name: 'First Series #1' })).toHaveAttribute('href', '/thread/3153?issue=1121330')
  fireEvent.click(screen.getByRole('button', { name: 'Load more' }))
  expect(loadMore).toHaveBeenCalledOnce()
})

it('keeps a deleted-series action readable without a fabricated link', () => {
  mockedUseActivity.mockReturnValue({
    events: [event(10, 'Rated a deleted issue', { thread_id: null, thread_title: null, issue_id: null, issue_number: null })],
    isPending: false, isRetrying: false, isError: false, error: null,
    isLoadingMore: false, hasMore: false, loadMore, refetch,
  })
  render(<MemoryRouter><HistoryPage /></MemoryRouter>)
  expect(screen.getByText('Deleted series')).toBeInTheDocument()
  expect(screen.queryByRole('link')).not.toBeInTheDocument()
})

it('offers retry when loading fails', () => {
  mockedUseActivity.mockReturnValue({
    events: [], isPending: false, isRetrying: false, isError: true, error: new Error('failed'),
    isLoadingMore: false, hasMore: false, loadMore, refetch,
  })
  render(<MemoryRouter><HistoryPage /></MemoryRouter>)
  expect(screen.getByRole('alert')).toHaveTextContent('Failed to load your history.')
  fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
  expect(refetch).toHaveBeenCalledOnce()
})
