import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
import HistoryPage from '../pages/HistoryPage'
import { useActivity } from '../hooks/useActivity'
import type { ActivityEvent } from '../services/api-activity'

vi.mock('../hooks/useActivity', () => ({ useActivity: vi.fn() }))

const mockedUseActivity = vi.mocked(useActivity)

type ActivityState = ReturnType<typeof useActivity>

function activityState(overrides: Partial<ActivityState> = {}): ActivityState {
  return {
    events: [],
    isPending: false,
    isRetrying: false,
    isError: false,
    isFetchNextPageError: false,
    error: null,
    isLoadingMore: false,
    hasMore: false,
    loadMore: vi.fn(),
    refetch: vi.fn(),
    ...overrides,
  }
}

function event(
  event_id: number,
  overrides: Partial<ActivityEvent> = {},
): ActivityEvent {
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
    action_display: 'Rolled First Series #1',
    ...overrides,
  }
}

function renderPage() {
  return render(
    <MemoryRouter>
      <HistoryPage />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  mockedUseActivity.mockReturnValue(activityState())
})

it('renders the empty activity state', () => {
  renderPage()

  expect(screen.getByRole('heading', { name: 'History' })).toBeInTheDocument()
  expect(screen.getByText('Your reading activity')).toBeInTheDocument()
  expect(screen.getByText('No activity yet')).toBeInTheDocument()
  expect(screen.queryByRole('list')).not.toBeInTheDocument()
})

it('keeps reader-facing export controls and internal export links out of history (issue #3572)', () => {
  renderPage()

  expect(screen.queryByRole('link', { name: /export summary/i })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /export summary/i })).not.toBeInTheDocument()
  expect(screen.queryByText(/export summary/i)).not.toBeInTheDocument()

  mockedUseActivity.mockReturnValue(activityState({ events: [event(1)] }))
  renderPage()

  expect(screen.queryByRole('link', { name: /export summary/i })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /export summary/i })).not.toBeInTheDocument()
  expect(screen.queryByText(/export summary/i)).not.toBeInTheDocument()

  const hrefs = Array.from(document.querySelectorAll('a')).map((a) => a.getAttribute('href'))
  expect(hrefs).not.toContain('/admin/export/summary/')
  expect(hrefs).not.toContain('/api/admin/export/summary/')
  expect(hrefs.filter((href) => (href ?? '').includes('/export/'))).toEqual([])
})

it('renders the reported 09:42 to 10:01 sequence in causal order with one rating row (issue #4822)', () => {
  mockedUseActivity.mockReturnValue(
    activityState({
      events: [
        event(7, {
          event_type: 'rate',
          timestamp: '2026-11-08T16:01:00Z',
          die_before: 10,
          die_after: 8,
          rating: 4.5,
          thread_id: 3480,
          thread_title: 'Third Series',
          issue_id: 1121332,
          issue_number: '2',
          action_display: 'Rated Third Series #2 ⭐4.5',
        }),
        event(4, {
          event_type: 'snooze',
          timestamp: '2026-11-08T15:58:00Z',
          die_before: 8,
          die_after: 10,
          thread_id: 3470,
          thread_title: 'Second Series',
          issue_id: null,
          issue_number: null,
          action_display: 'Snoozed Second Series (d8 → d10)',
        }),
        event(5, {
          event_type: 'roll',
          timestamp: '2026-11-08T15:55:00Z',
          thread_id: 3480,
          thread_title: 'Third Series',
          issue_id: 1121332,
          issue_number: '2',
          action_display: 'Rolled Third Series #2',
        }),
        event(2, {
          event_type: 'snooze',
          timestamp: '2026-11-08T15:50:00Z',
          die_before: 6,
          die_after: 8,
          thread_id: 3153,
          thread_title: 'First Series',
          issue_id: null,
          issue_number: null,
          action_display: 'Snoozed First Series (d6 → d8)',
        }),
        event(3, {
          event_type: 'roll',
          timestamp: '2026-11-08T15:48:00Z',
          thread_id: 3469,
          thread_title: 'Second Series',
          issue_id: 1121331,
          issue_number: '2',
          action_display: 'Rolled Second Series #2',
        }),
        event(1, {
          timestamp: '2026-11-08T15:42:35.028Z',
          thread_id: 3153,
          thread_title: 'First Series',
          issue_id: 1121330,
          issue_number: '1',
          action_display: 'Rolled First Series #1',
        }),
      ],
    }),
  )

  renderPage()

  const rows = screen.getAllByRole('listitem')
  expect(rows).toHaveLength(6)
  expect(rows.map((row) => row.textContent)).toEqual([
    expect.stringContaining('Rated Third Series #2 ⭐4.5'),
    expect.stringContaining('Snoozed Second Series (d8 → d10)'),
    expect.stringContaining('Rolled Third Series #2'),
    expect.stringContaining('Snoozed First Series (d6 → d8)'),
    expect.stringContaining('Rolled Second Series #2'),
    expect.stringContaining('Rolled First Series #1'),
  ])

  // The server folds the dice/issue rate receipts into exactly one visible row.
  expect(screen.getAllByText(/⭐4\.5/)).toHaveLength(1)
  expect(screen.getAllByText(/^Snoozed /)).toHaveLength(2)
  expect(screen.getAllByText(/^Rolled /)).toHaveLength(3)

  // The row keeps the server timestamp as its machine-readable time value.
  expect(rows[0]?.querySelector('time')).toHaveAttribute(
    'dateTime',
    '2026-11-08T16:01:00Z',
  )
  expect(rows[5]?.querySelector('time')).toHaveAttribute(
    'dateTime',
    '2026-11-08T15:42:35.028Z',
  )
})

it('renders historical manual-die and reset rows with their recorded labels', () => {
  mockedUseActivity.mockReturnValue(
    activityState({
      events: [
        event(3, {
          event_type: 'reset_dice',
          timestamp: '2026-11-08T16:20:00Z',
          die_before: null,
          die_after: null,
          thread_id: null,
          thread_title: null,
          issue_id: null,
          issue_number: null,
          action_display: 'Reset dice',
        }),
        event(2, {
          event_type: 'manual_die',
          timestamp: '2026-11-08T16:10:00Z',
          die_before: 8,
          die_after: null,
          thread_id: null,
          thread_title: null,
          issue_id: null,
          issue_number: null,
          action_display: 'Manual die selection (d8)',
        }),
        event(1, {
          event_type: 'rate',
          timestamp: '2026-11-08T16:00:00Z',
          rating: null,
          thread_title: 'First Series',
          issue_number: '4',
          action_display: 'Read First Series #4',
        }),
      ],
    }),
  )

  renderPage()

  expect(screen.getByText('Reset dice')).toBeInTheDocument()
  expect(screen.getByText('Manual die selection (d8)')).toBeInTheDocument()
  expect(screen.getByText('Read First Series #4')).toBeInTheDocument()
  // Historical rows without a live thread offer no fabricated navigation.
  expect(screen.getAllByRole('link')).toHaveLength(1)
  expect(screen.getByRole('link')).toHaveAttribute('href', '/thread/3153?issue=1121330')
})

it('labels deleted identities safely without fabricating a link', () => {
  mockedUseActivity.mockReturnValue(
    activityState({
      events: [
        event(2, {
          thread_id: null,
          thread_title: null,
          issue_id: null,
          issue_number: null,
          action_display: 'Rolled a series that is no longer available',
        }),
        event(1, {
          thread_id: null,
          thread_title: null,
          issue_id: 991,
          issue_number: '5',
          action_display: 'Marked issue #5 unread',
        }),
      ],
    }),
  )

  renderPage()

  expect(screen.getByText(/a series that is no longer available/)).toBeInTheDocument()
  expect(screen.getByText('Marked issue #5 unread')).toBeInTheDocument()
  expect(screen.getByText('Deleted series')).toBeInTheDocument()
  expect(screen.getByText('Deleted series #5')).toBeInTheDocument()
  expect(screen.queryByRole('link')).not.toBeInTheDocument()
  expect(screen.queryByText(/\/thread\/null/)).not.toBeInTheDocument()
})

it('links a live thread and its issue, and a thread without an issue', () => {
  mockedUseActivity.mockReturnValue(
    activityState({
      events: [
        event(2, {
          thread_id: 12,
          thread_title: 'Big Shot',
          issue_id: null,
          issue_number: null,
          action_display: 'Rolled Big Shot',
        }),
        event(1, {
          thread_id: 3153,
          thread_title: 'First Series',
          issue_id: 1121330,
          issue_number: '1',
          action_display: 'Rolled First Series #1',
        }),
      ],
    }),
  )

  renderPage()

  expect(screen.getByRole('link', { name: 'Big Shot' })).toHaveAttribute(
    'href',
    '/thread/12',
  )
  expect(screen.getByRole('link', { name: 'First Series #1' })).toHaveAttribute(
    'href',
    '/thread/3153?issue=1121330',
  )
})

it('loads more activity from the server cursor and offers a load-more retry', () => {
  const loadMore = vi.fn()
  mockedUseActivity.mockReturnValue(
    activityState({ events: [event(1)], hasMore: true, loadMore }),
  )
  const { rerender } = renderPage()

  fireEvent.click(screen.getByRole('button', { name: 'Load More Activity' }))
  expect(loadMore).toHaveBeenCalledTimes(1)

  mockedUseActivity.mockReturnValue(
    activityState({ events: [event(1)], isLoadingMore: true, hasMore: true, loadMore }),
  )
  rerender(
    <MemoryRouter>
      <HistoryPage />
    </MemoryRouter>,
  )
  expect(screen.getByText('Loading more...')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Load More Activity' })).not.toBeInTheDocument()

  mockedUseActivity.mockReturnValue(
    activityState({
      events: [event(1)],
      isError: true,
      isFetchNextPageError: true,
      error: new Error('page 2'),
      loadMore,
    }),
  )
  rerender(
    <MemoryRouter>
      <HistoryPage />
    </MemoryRouter>,
  )
  expect(screen.getByText('Failed to load more history')).toBeInTheDocument()
  // The already-loaded page stays visible while the next page is retried.
  expect(screen.getByText('Rolled First Series #1')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
  expect(loadMore).toHaveBeenCalledTimes(2)
})

it('retries the refresh, not the next page, when a background refresh fails', () => {
  const loadMore = vi.fn()
  const refetch = vi.fn()
  mockedUseActivity.mockReturnValue(
    activityState({
      events: [event(1)],
      isError: true,
      isFetchNextPageError: false,
      error: new Error('refresh failed'),
      loadMore,
      refetch,
    }),
  )
  renderPage()

  expect(screen.getByText('Failed to refresh history')).toBeInTheDocument()
  expect(screen.queryByText('Failed to load more history')).not.toBeInTheDocument()
  expect(screen.getByText('Rolled First Series #1')).toBeInTheDocument()

  fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
  expect(refetch).toHaveBeenCalledTimes(1)
  expect(loadMore).not.toHaveBeenCalled()
})

it('refreshes the current activity query without dropping the list', () => {
  const refetch = vi.fn()
  mockedUseActivity.mockReturnValue(activityState({ events: [event(1)], refetch }))
  renderPage()

  fireEvent.click(screen.getByRole('button', { name: 'Refresh' }))
  expect(refetch).toHaveBeenCalledTimes(1)
  expect(screen.getByText('Rolled First Series #1')).toBeInTheDocument()
})

it('holds a bare spinner before any initial attempt has failed (issue #3429)', () => {
  mockedUseActivity.mockReturnValue(activityState({ isPending: true }))
  renderPage()

  expect(screen.getByText('Loading...')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument()
})

it('offers Retry without a reload once an initial attempt has failed (issue #3429)', () => {
  const refetch = vi.fn()
  mockedUseActivity.mockReturnValue(
    activityState({ isPending: true, isRetrying: true, refetch }),
  )
  renderPage()

  expect(screen.getByRole('status')).toHaveTextContent('Still loading your history')
  fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
  expect(refetch).toHaveBeenCalledTimes(1)
})

it('offers Retry on an initial load failure (issue #3429)', () => {
  const refetch = vi.fn()
  mockedUseActivity.mockReturnValue(
    activityState({ isError: true, error: new Error('timeout of 10000ms exceeded'), refetch }),
  )
  renderPage()

  expect(screen.getByRole('alert')).toHaveTextContent('Failed to load history')
  fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
  expect(refetch).toHaveBeenCalledTimes(1)
})

it('renders an unparseable timestamp verbatim instead of inventing one', () => {
  mockedUseActivity.mockReturnValue(
    activityState({ events: [event(1, { timestamp: 'not-a-timestamp' })] }),
  )
  renderPage()

  expect(screen.getByText('not-a-timestamp')).toBeInTheDocument()
})
