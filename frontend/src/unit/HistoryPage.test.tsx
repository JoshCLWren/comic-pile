import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
import HistoryPage from '../pages/HistoryPage'
import { useActivity } from '../hooks/useActivity'

vi.mock('../hooks/useActivity', () => ({ useActivity: vi.fn() }))

// SAFETY: the module is mocked, so the test supplies the return shape directly
const mockedUseActivity = vi.mocked(useActivity) as any

const mockActivityResponse = {
  events: [] as any[],
  next_page_token: null as string | null,
}

beforeEach(() => {
  mockedUseActivity.mockReturnValue({
    events: [],
    isPending: false,
    isLoadingMore: false,
    hasMore: false,
    loadMore: vi.fn(),
    error: null,
    isError: false,
    refetch: vi.fn(),
    isRetrying: false,
  })
})

it('renders empty history state', () => {
  render(
    <MemoryRouter>
      <HistoryPage />
    </MemoryRouter>
  )

  expect(screen.getByText('History')).toBeInTheDocument()
  expect(screen.getByText('No activity yet')).toBeInTheDocument()
})

it('shows history page header for empty state', () => {
  render(
    <MemoryRouter>
      <HistoryPage />
    </MemoryRouter>
  )

  expect(screen.getByText('History')).toBeInTheDocument()
  expect(screen.getByText('Your reading activity history')).toBeInTheDocument()
  expect(screen.getByText('No activity yet')).toBeInTheDocument()
})

it('renders activity events from the activity API', () => {
  mockedUseActivity.mockReturnValue({
    events: [
      {
        event_id: 1,
        type: 'roll',
        timestamp: '2024-01-01T10:00:00Z',
        die_before: 6,
        die_after: 8,
        rating: null,
        thread_id: 1,
        thread_title: 'Saga',
        issue_number: '1',
      },
      {
        event_id: 2,
        type: 'rate',
        timestamp: '2024-01-01T10:15:00Z',
        die_before: 8,
        die_after: null,
        rating: 4.5,
        thread_id: 1,
        thread_title: 'Saga',
        issue_number: '1',
      },
    ],
    isPending: false,
    isLoadingMore: false,
    hasMore: false,
    loadMore: vi.fn(),
    error: null,
    isError: false,
    refetch: vi.fn(),
    isRetrying: false,
  })

  render(<MemoryRouter><HistoryPage /></MemoryRouter>)

  const listitem = screen.getByRole('listitem')
  expect(listitem).toBeInTheDocument()

  // Should have two events
  const eventItems = screen.getAllByRole('listitem')
  expect(eventItems).toHaveLength(2)

  // Check first event (roll)
  expect(screen.getByText('Saga')).toBeInTheDocument()
})

it('renders a rated event with correct details', () => {
  mockedUseActivity.mockReturnValue({
    events: [
      {
        event_id: 1,
        type: 'rate',
        timestamp: '2024-01-01T10:00:00Z',
        die_before: 6,
        die_after: 8,
        rating: 4.5,
        thread_id: 1,
        thread_title: 'Saga',
        issue_number: '1',
      },
    ],
    isPending: false,
    isLoadingMore: false,
    hasMore: false,
    loadMore: vi.fn(),
    error: null,
    isError: false,
    refetch: vi.fn(),
    isRetrying: false,
  })

  render(<MemoryRouter><HistoryPage /></MemoryRouter>)

  expect(screen.getByText('Saga')).toBeInTheDocument()
  expect(screen.getByText('#1')).toBeInTheDocument()
  expect(screen.getByText('Rated 4.5')).toBeInTheDocument()
  expect(screen.getByText('d6 → d8')).toBeInTheDocument()
})

it('renders a rolled event with correct details', () => {
  mockedUseActivity.mockReturnValue({
    events: [
      {
        event_id: 1,
        type: 'roll',
        timestamp: '2024-01-01T10:00:00Z',
        die_before: 20,
        die_after: 8,
        rating: null,
        thread_id: 1,
        thread_title: 'Hulk',
        issue_number: '5',
      },
    ],
    isPending: false,
    isLoadingMore: false,
    hasMore: false,
    loadMore: vi.fn(),
    error: null,
    isError: false,
    refetch: vi.fn(),
    isRetrying: false,
  })

  render(<MemoryRouter><HistoryPage /></MemoryRouter>)

  expect(screen.getByText('Hulk')).toBeInTheDocument()
  expect(screen.getByText('#5')).toBeInTheDocument()
  // Roll events show dice progression, not rolled result (result not in activity API)
  expect(screen.getByText('d20 → d8')).toBeInTheDocument()
})

it('renders a snooze event with correct details', () => {
  mockedUseActivity.mockReturnValue({
    events: [
      {
        event_id: 1,
        type: 'snooze',
        timestamp: '2024-01-01T10:00:00Z',
        die_before: 6,
        die_after: 8,
        rating: null,
        thread_id: 1,
        thread_title: 'Saga',
        issue_number: null,
      },
    ],
    isPending: false,
    isLoadingMore: false,
    hasMore: false,
    loadMore: vi.fn(),
    error: null,
    isError: false,
    refetch: vi.fn(),
    isRetrying: false,
  })

  render(<MemoryRouter><HistoryPage /></MemoryRouter>)

  expect(screen.getByText('Saga')).toBeInTheDocument()
  expect(screen.getByText('Snoozed')).toBeInTheDocument()
  expect(screen.getByText('d6 → d8')).toBeInTheDocument()
})

it('renders event without issue number', () => {
  mockedUseActivity.mockReturnValue({
    events: [
      {
        event_id: 1,
        type: 'rate',
        timestamp: '2024-01-01T10:00:00Z',
        die_before: 6,
        die_after: null,
        rating: 3.5,
        thread_id: 1,
        thread_title: 'Unknown Thread',
        issue_number: null,
      },
    ],
    isPending: false,
    isLoadingMore: false,
    hasMore: false,
    loadMore: vi.fn(),
    error: null,
    isError: false,
    refetch: vi.fn(),
    isRetrying: false,
  })

  render(<MemoryRouter><HistoryPage /></MemoryRouter>)

  expect(screen.getByText('Unknown Thread')).toBeInTheDocument()
  expect(screen.getByText('Rated 3.5')).toBeInTheDocument()
})

it('renders event type labels correctly', () => {
  mockedUseActivity.mockReturnValue({
    events: [
      {
        event_id: 1,
        type: 'unsnooze',
        timestamp: '2024-01-01T10:00:00Z',
        die_before: 6,
        die_after: null,
        rating: null,
        thread_id: 1,
        thread_title: 'Saga',
        issue_number: null,
      },
    ],
    isPending: false,
    isLoadingMore: false,
    hasMore: false,
    loadMore: vi.fn(),
    error: null,
    isError: false,
    refetch: vi.fn(),
    isRetrying: false,
  })

  render(<MemoryRouter><HistoryPage /></MemoryRouter>)

  expect(screen.getByText('Unsnoozed')).toBeInTheDocument()
})

it('shows no activity message when events array is empty', () => {
  mockedUseActivity.mockReturnValue({
    events: [],
    isPending: false,
    isLoadingMore: false,
    hasMore: false,
    loadMore: vi.fn(),
    error: null,
    isError: false,
    refetch: vi.fn(),
    isRetrying: false,
  })

  render(<MemoryRouter><HistoryPage /></MemoryRouter>)

  expect(screen.getByText('No activity yet')).toBeInTheDocument()
})

it('renders loading and error states', () => {
  mockedUseActivity.mockReturnValue({ events: [], isPending: true, isLoadingMore: false, hasMore: false, loadMore: vi.fn() })
  const { rerender } = render(<MemoryRouter><HistoryPage /></MemoryRouter>)
  expect(screen.getByText('Loading...')).toBeInTheDocument()
  
  mockedUseActivity.mockReturnValue({ events: [], isPending: false, isLoadingMore: false, hasMore: false, loadMore: vi.fn(), error: new Error('no'), isError: true })
  rerender(<MemoryRouter><HistoryPage /></MemoryRouter>)
  expect(screen.getByText('Failed to load activity history')).toBeInTheDocument()
})

it('shows Load More button when hasMore is true', () => {
  const loadMore = vi.fn()
  mockedUseActivity.mockReturnValue({
    events: [{ event_id: 1, type: 'roll', timestamp: '2024-01-01T10:00:00Z', die_before: 6, die_after: null, rating: null, thread_id: 1, thread_title: 'Saga', issue_number: null }],
    isPending: false,
    isLoadingMore: false,
    hasMore: true,
    loadMore,
    error: null,
    isError: false,
    refetch: vi.fn(),
    isRetrying: false,
  })
  render(<MemoryRouter><HistoryPage /></MemoryRouter>)
  const button = screen.getByText('Load More Events')
  expect(button).toBeInTheDocument()
  fireEvent.click(button)
  expect(loadMore).toHaveBeenCalledTimes(1)
})

it('shows loading state when loading more', () => {
  mockedUseActivity.mockReturnValue({
    events: [{ event_id: 1, type: 'roll', timestamp: '2024-01-01T10:00:00Z', die_before: 6, die_after: null, rating: null, thread_id: 1, thread_title: 'Saga', issue_number: null }],
    isPending: false,
    isLoadingMore: true,
    hasMore: false,
    loadMore: vi.fn(),
    error: null,
    isError: false,
    refetch: vi.fn(),
    isRetrying: false,
  })
  render(<MemoryRouter><HistoryPage /></MemoryRouter>)
  expect(screen.getByText('Loading more...')).toBeInTheDocument()
})

it('shows retry button on load more error', () => {
  const loadMore = vi.fn()
  mockedUseActivity.mockReturnValue({
    events: [{ event_id: 1, type: 'roll', timestamp: '2024-01-01T10:00:00Z', die_before: 6, die_after: null, rating: null, thread_id: 1, thread_title: 'Saga', issue_number: null }],
    isPending: false,
    isLoadingMore: false,
    hasMore: false,
    loadMore,
    error: new Error('load more failed'),
    isError: true,
    refetch: vi.fn(),
    isRetrying: false,
  })
  render(<MemoryRouter><HistoryPage /></MemoryRouter>)
  expect(screen.getByText('Failed to load more events')).toBeInTheDocument()
  const retryButton = screen.getByText('Retry')
  expect(retryButton).toBeInTheDocument()
  fireEvent.click(retryButton)
  expect(loadMore).toHaveBeenCalledTimes(1)
})

it('holds a bare spinner before any initial attempt has failed (issue #3429)', () => {
  mockedUseActivity.mockReturnValue({
    events: [],
    isPending: true,
    isLoadingMore: false,
    hasMore: false,
    loadMore: vi.fn(),
    error: null,
    isError: false,
    isRetrying: false,
    refetch: vi.fn(),
  })
  render(<MemoryRouter><HistoryPage /></MemoryRouter>)
  expect(screen.getByText('Loading...')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument()
})

it('offers Retry without a reload once an initial attempt has failed (issue #3429)', () => {
  const refetch = vi.fn()
  mockedUseActivity.mockReturnValue({
    events: [],
    isPending: true,
    isLoadingMore: false,
    hasMore: false,
    loadMore: vi.fn(),
    error: null,
    isError: false,
    isRetrying: true,
    refetch,
  })
  render(<MemoryRouter><HistoryPage /></MemoryRouter>)
  expect(screen.getByRole('status')).toHaveTextContent('Still loading your history')
  fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
  expect(refetch).toHaveBeenCalledTimes(1)
})

it('offers Retry on an initial load failure (issue #3429)', () => {
  const refetch = vi.fn()
  mockedUseActivity.mockReturnValue({
    events: [],
    isPending: false,
    isLoadingMore: false,
    hasMore: false,
    loadMore: vi.fn(),
    error: new Error('timeout of 10000ms exceeded'),
    isError: true,
    isRetrying: false,
    refetch,
  })
  render(<MemoryRouter><HistoryPage /></MemoryRouter>)
  expect(screen.getByRole('alert')).toHaveTextContent('Failed to load activity history')
  fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
  expect(refetch).toHaveBeenCalledTimes(1)
})

it('keeps the bounded loading state visible during a user-initiated retry (issue #3429)', () => {
  const refetch = vi.fn()
  mockedUseActivity.mockReturnValue({
    events: [],
    isPending: true,
    isLoadingMore: false,
    hasMore: false,
    loadMore: vi.fn(),
    error: null,
    isError: false,
    isRetrying: true,
    refetch,
  })
  render(<MemoryRouter><HistoryPage /></MemoryRouter>)
  expect(screen.getByRole('status')).toHaveTextContent('Still loading your history')
  expect(screen.queryByText('Loading...')).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
})

it('renders multiple events chronologically', () => {
  mockedUseActivity.mockReturnValue({
    events: [
      {
        event_id: 10,
        type: 'roll',
        timestamp: '2024-01-01T10:03:00Z',
        die_before: 6,
        die_after: 8,
        rating: null,
        thread_id: 1,
        thread_title: 'Saga',
        issue_number: '2',
      },
      {
        event_id: 9,
        type: 'snooze',
        timestamp: '2024-01-01T10:02:00Z',
        die_before: 8,
        die_after: 10,
        rating: null,
        thread_id: 1,
        thread_title: 'Saga',
        issue_number: null,
      },
      {
        event_id: 8,
        type: 'roll',
        timestamp: '2024-01-01T10:01:00Z',
        die_before: 6,
        die_after: 8,
        rating: null,
        thread_id: 1,
        thread_title: 'Saga',
        issue_number: '1',
      },
      {
        event_id: 7,
        type: 'rate',
        timestamp: '2024-01-01T10:00:00Z',
        die_before: 8,
        die_after: null,
        rating: 4.5,
        thread_id: 1,
        thread_title: 'Saga',
        issue_number: '1',
      },
    ],
    isPending: false,
    isLoadingMore: false,
    hasMore: false,
    loadMore: vi.fn(),
    error: null,
    isError: false,
    refetch: vi.fn(),
    isRetrying: false,
  })

  render(<MemoryRouter><HistoryPage /></MemoryRouter>)

  // Check that events are displayed
  expect(screen.getByText('Saga')).toBeInTheDocument()
  expect(screen.getByText('Rated 4.5')).toBeInTheDocument()
  
  // Check die progressions are shown
  const diceProgressions = screen.getAllByText(/d\d/)
  expect(diceProgressions.length).toBeGreaterThan(0)
})