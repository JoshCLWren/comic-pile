import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
import HistoryPage from '../pages/HistoryPage'
import { useSessions } from '../hooks/useSession'

vi.mock('../hooks/useSession', () => ({ useSessions: vi.fn() }))

// SAFETY: the module is mocked, so the test supplies the return shape directly
const mockedUseSessions = vi.mocked(useSessions) as any

beforeEach(() => {
  mockedUseSessions.mockReturnValue({ data: [], isLoading: false, hasMore: false, loadMore: vi.fn(), isLoadingMore: false })
})

it('renders empty history state', () => {
  render(
    <MemoryRouter>
      <HistoryPage />
    </MemoryRouter>
  )

  expect(screen.getByText('History')).toBeInTheDocument()
  expect(screen.getByText('No sessions yet')).toBeInTheDocument()
})

it('shows no Export Summary control or internal export link in the empty state (issue #3572)', () => {
  render(
    <MemoryRouter>
      <HistoryPage />
    </MemoryRouter>
  )

  // The owner-approved removal takes the dead reader-facing export out of the
  // empty branch too, while the header copy and empty-state navigation stay.
  expect(screen.getByText('History')).toBeInTheDocument()
  expect(screen.getByText('Your reading session history')).toBeInTheDocument()
  expect(screen.getByText('No sessions yet')).toBeInTheDocument()

  expect(screen.queryByRole('link', { name: /export summary/i })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /export summary/i })).not.toBeInTheDocument()
  expect(screen.queryByText(/export summary/i)).not.toBeInTheDocument()

  const hrefs = Array.from(document.querySelectorAll('a')).map((a) => a.getAttribute('href'))
  expect(hrefs).not.toContain('/admin/export/summary/')
  expect(hrefs).not.toContain('/api/admin/export/summary/')
  expect(hrefs.filter((href) => (href ?? '').includes('/export/'))).toEqual([])
})

it('keeps sessions and navigation without any Export Summary control or internal export link (issue #3572)', () => {
  mockedUseSessions.mockReturnValue({
    data: [{
      id: 31,
      started_at: '2024-01-01T10:00:00Z',
      ended_at: '2024-01-01T10:30:00Z',
      ladder_path: '6',
      active_thread: { title: 'Saga', format: 'Comic', next_issue_number: '13', issues_read: 2, last_rating: 4.5 },
      last_rolled_result: 4,
      current_die: 6,
      start_die: 6,
      snapshot_count: 1,
    }],
    isPending: false,
    isLoadingMore: false,
    hasMore: false,
    loadMore: vi.fn(),
    error: null,
  })

  render(<MemoryRouter><HistoryPage /></MemoryRouter>)

  // Normal history rendering and navigation are untouched by the removal.
  expect(screen.getByText('History')).toBeInTheDocument()
  expect(screen.getByText('Saga')).toBeInTheDocument()
  expect(screen.getByRole('list')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /view full session/i })).toHaveAttribute('href', '/sessions/31')
  expect(screen.getByText('Snapshots (1)')).toBeInTheDocument()

  expect(screen.queryByRole('link', { name: /export summary/i })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /export summary/i })).not.toBeInTheDocument()
  expect(screen.queryByText(/export summary/i)).not.toBeInTheDocument()

  const hrefs = Array.from(document.querySelectorAll('a')).map((a) => a.getAttribute('href'))
  expect(hrefs).not.toContain('/admin/export/summary/')
  expect(hrefs).not.toContain('/api/admin/export/summary/')
  expect(hrefs.filter((href) => (href ?? '').includes('/export/'))).toEqual([])
})

it('labels an empty session as No issue selected', () => {
  mockedUseSessions.mockReturnValue({
    data: [{
      id: 9,
      started_at: '2024-01-01T10:00:00Z',
      ended_at: null,
      ladder_path: '6',
      active_thread: null,
      last_rolled_result: null,
      current_die: 6,
      start_die: 6,
      snapshot_count: 1,
    }],
    isPending: false,
    isLoadingMore: false,
    hasMore: false,
    loadMore: vi.fn(),
    error: null,
  })

  render(<MemoryRouter><HistoryPage /></MemoryRouter>)

  expect(screen.getByText('No issue selected')).toBeInTheDocument()
  // The card still reports the start die so an empty session is never a
  // summary-free card (#3573).
  expect(screen.getByText('d6')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /view full session/i })).toHaveAttribute(
    'href',
    '/sessions/9',
  )
})

it('does not label an active session with a rolled result as abandoned', () => {
  mockedUseSessions.mockReturnValue({
    data: [{
      id: 10,
      started_at: '2024-01-01T10:00:00Z',
      ended_at: null,
      ladder_path: '6 → 8',
      active_thread: { title: 'Saga', format: 'Comic' },
      last_rolled_result: 4,
      current_die: 8,
      start_die: 8,
      snapshot_count: 3,
    }],
    isPending: false,
    isLoadingMore: false,
    hasMore: false,
    loadMore: vi.fn(),
    error: null,
  })

  render(<MemoryRouter><HistoryPage /></MemoryRouter>)

  expect(screen.queryByText('No issue selected')).not.toBeInTheDocument()
  expect(screen.queryByText('Abandoned roll')).not.toBeInTheDocument()
  expect(screen.getByText('Saga')).toBeInTheDocument()
})

it('leads with comic identity and readable activity summary for a typical rated session', () => {
  mockedUseSessions.mockReturnValue({
    data: [{
      id: 11,
      started_at: '2024-08-23T10:00:00Z',
      ended_at: '2024-08-23T10:45:00Z',
      ladder_path: '6 → 4 → 6',
      active_thread: {
        title: 'Cable',
        format: 'Comic',
        next_issue_number: '62',
        issues_read: 1,
        last_rating: 4.5,
      },
      last_rolled_result: 3,
      current_die: 6,
      start_die: 6,
      snapshot_count: 2,
    }],
    isPending: false,
    isLoadingMore: false,
    hasMore: false,
    loadMore: vi.fn(),
    error: null,
  })

  render(<MemoryRouter><HistoryPage /></MemoryRouter>)

  const listitem = screen.getByRole('listitem')
  expect(listitem).toBeInTheDocument()

  const titleBlock = listitem.querySelector('p.font-bold')
  expect(titleBlock).not.toBeNull()
  expect(titleBlock!.textContent).toContain('Cable')
  expect(titleBlock!.textContent).toContain('#62')

  expect(screen.getByText(/1 issue read/)).toBeInTheDocument()
  expect(screen.getByText(/rated 4\.5/)).toBeInTheDocument()

  const dieLine = screen.getByText('d6 → d4 → d6 · Rolled 3')
  expect(dieLine).toBeInTheDocument()
  expect(dieLine).toHaveClass('text-[var(--theme-text-dim)]')
  expect(listitem).toContainElement(dieLine)
  // The progression and the roll stay visible exactly once for a rated card.
  expect(screen.getAllByText(/^d\d/)).toHaveLength(1)

  // Check that activity line contains read/rating info with die size
  const activityLine = listitem.querySelector('p.text-xs')
  expect(activityLine).not.toBeNull()
  expect(activityLine!.textContent).toContain('1 issue read')
  expect(activityLine!.textContent).toContain('rated 4.5')
  expect(activityLine!.textContent).toContain('Die size d6')

  const headlineIndex = listitem.children[1]!.children[0]!.compareDocumentPosition(dieLine)
  expect(headlineIndex & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
})

it('keeps the queue position and dice progression on a card without reading activity', () => {
  mockedUseSessions.mockReturnValue({
    data: [{
      id: 13,
      started_at: '2024-10-05T13:10:00Z',
      ended_at: null,
      ladder_path: '20',
      active_thread: {
        title: 'Hulk',
        format: 'Comic',
        next_issue_number: '5',
        issues_remaining: 3,
        issues_read: 0,
        last_rating: null,
      },
      last_rolled_result: 7,
      current_die: 20,
      start_die: 20,
      snapshot_count: 1,
    }],
    isPending: false,
    isLoadingMore: false,
    hasMore: false,
    loadMore: vi.fn(),
    error: null,
  })

  render(<MemoryRouter><HistoryPage /></MemoryRouter>)

  const listitem = screen.getByRole('listitem')
  expect(screen.getByText('Hulk')).toBeInTheDocument()
  expect(screen.getByText('3 left in queue')).toBeInTheDocument()
  expect(screen.getByText('d20 · Rolled 7')).toBeInTheDocument()
  expect(listitem).toContainElement(screen.getByText('d20 · Rolled 7'))
  expect(screen.getAllByText(/^d\d/)).toHaveLength(1)
})

it('pluralizes issues read for multi-issue activity', () => {
  mockedUseSessions.mockReturnValue({
    data: [{
      id: 12,
      started_at: '2024-01-01T10:00:00Z',
      ended_at: '2024-01-01T10:30:00Z',
      ladder_path: '20',
      active_thread: {
        title: 'Saga',
        format: 'Comic',
        next_issue_number: '13',
        issues_read: 3,
        last_rating: 4.5,
      },
      last_rolled_result: 7,
      current_die: 20,
      start_die: 20,
      snapshot_count: 2,
    }],
    isPending: false,
    isLoadingMore: false,
    hasMore: false,
    loadMore: vi.fn(),
    error: null,
  })

  render(<MemoryRouter><HistoryPage /></MemoryRouter>)

  expect(screen.getByText(/3 issues read/)).toBeInTheDocument()
  expect(screen.getByText(/rated 4\.5/)).toBeInTheDocument()
})

it('renders session rows with metadata, duration, and footer links', () => {
  mockedUseSessions.mockReturnValue({ data: [
    { id: 1, started_at: '2024-01-01T10:00:00Z', ended_at: '2024-01-01T10:05:00Z', ladder_path: '6 → 8', active_thread: { title: 'Saga', format: 'Comic', next_issue_number: '13', issues_read: 3, last_rating: 4.5 }, last_rolled_result: 4, current_die: 6,
      start_die: 6, snapshot_count: 2 },
    { id: 2, started_at: '2024-01-01T10:00:00Z', ended_at: '2024-01-01T11:00:00Z', ladder_path: null, active_thread: null, snapshot_count: 0 },
    { id: 3, started_at: '2024-01-01T10:00:00Z', ended_at: '2024-01-01T12:30:00Z', ladder_path: '20', active_thread: { title: 'Other', format: 'Manga' }, last_rolled_result: null, current_die: 20,
      start_die: 20, snapshot_count: 1 },
    { id: 4, started_at: 'bad', ended_at: null, ladder_path: null, active_thread: null, start_die: null },
    { id: 5, started_at: '2024-01-01T12:00:00Z', ended_at: '2024-01-01T11:00:00Z', ladder_path: '', active_thread: { title: 'Zero', format: 'Comic' }, last_rolled_result: 0, current_die: 4,
      start_die: 4, snapshot_count: 0 },
    { id: 6, started_at: 'bad', ended_at: 'bad', ladder_path: '6', active_thread: null, start_die: 6, snapshot_count: 0 },
    { id: 7, started_at: null, ended_at: 'bad', ladder_path: null, active_thread: null, start_die: null, snapshot_count: null },
    { id: 8, started_at: 'bad', ended_at: 'bad', ladder_path: null, active_thread: null, start_die: null, snapshot_count: null },
  ], isPending: false })
  render(<MemoryRouter><HistoryPage /></MemoryRouter>)
  expect(screen.getByRole('list')).toBeInTheDocument()
  // One dice progression line per session that has a ladder path.
  expect(screen.getAllByText(/^d\d/)).toHaveLength(3)
  expect(screen.getByText(/d6 → d8/)).toBeInTheDocument()
  expect(screen.getByText(/Rolled 4/)).toBeInTheDocument()
  expect(screen.queryByText(/Rolled 0/)).not.toBeInTheDocument()
  expect(screen.queryByText(/Dice progression:/)).not.toBeInTheDocument()
  expect(screen.getByText(/#13/)).toBeInTheDocument()
  expect(screen.getByText(/3 issues read/)).toBeInTheDocument()
  expect(screen.getByText(/rated 4\.5/)).toBeInTheDocument()
  expect(screen.getByText('Duration: 5m')).toBeInTheDocument()
  expect(screen.getByText('Duration: 1h')).toBeInTheDocument()
  expect(screen.getByText('Duration: 2h 30m')).toBeInTheDocument()
  const snapshotsLink = screen.getByText('Snapshots (2)')
  expect(snapshotsLink).toBeInTheDocument()
  expect(snapshotsLink.closest('a')).toHaveAttribute('href', '/sessions/1')
})

it('renders loading and error states', () => {
  mockedUseSessions.mockReturnValue({ data: null, isPending: true, isLoadingMore: false, hasMore: false, loadMore: vi.fn() })
  const { rerender } = render(<MemoryRouter><HistoryPage /></MemoryRouter>)
  expect(screen.getByText('Loading...')).toBeInTheDocument()
  mockedUseSessions.mockReturnValue({ data: null, isPending: false, isLoadingMore: false, hasMore: false, loadMore: vi.fn(), error: new Error('no') })
  rerender(<MemoryRouter><HistoryPage /></MemoryRouter>)
  expect(screen.getByText('Failed to load sessions')).toBeInTheDocument()
})

it('shows Load More button when hasMore is true', () => {
  const loadMore = vi.fn()
  mockedUseSessions.mockReturnValue({
    data: [{ id: 1, started_at: '2024-01-01T10:00:00Z', ended_at: null, ladder_path: null, active_thread: null, last_rolled_result: null, current_die: null, start_die: null, snapshot_count: null }],
    isPending: false,
    isLoadingMore: false,
    hasMore: true,
    loadMore,
    error: null,
  })
  render(<MemoryRouter><HistoryPage /></MemoryRouter>)
  const button = screen.getByText('Load More Sessions')
  expect(button).toBeInTheDocument()
  fireEvent.click(button)
  expect(loadMore).toHaveBeenCalledTimes(1)
})

it('shows loading state when loading more', () => {
  mockedUseSessions.mockReturnValue({
    data: [{ id: 1, started_at: '2024-01-01T10:00:00Z', ended_at: null, ladder_path: null, active_thread: null, last_rolled_result: null, current_die: null, start_die: null, snapshot_count: null }],
    isPending: false,
    isLoadingMore: true,
    hasMore: false,
    loadMore: vi.fn(),
    error: null,
  })
  render(<MemoryRouter><HistoryPage /></MemoryRouter>)
  expect(screen.getByText('Loading more...')).toBeInTheDocument()
})

it('shows retry button on load more error', () => {
  const loadMore = vi.fn()
  mockedUseSessions.mockReturnValue({
    data: [{ id: 1, started_at: '2024-01-01T10:00:00Z', ended_at: null, ladder_path: null, active_thread: null, last_rolled_result: null, current_die: null, start_die: null, snapshot_count: null }],
    isPending: false,
    isLoadingMore: false,
    hasMore: false,
    loadMore,
    error: new Error('load more failed'),
  })
  render(<MemoryRouter><HistoryPage /></MemoryRouter>)
  expect(screen.getByText('Failed to load more sessions')).toBeInTheDocument()
  const retryButton = screen.getByText('Retry')
  expect(retryButton).toBeInTheDocument()
  fireEvent.click(retryButton)
  expect(loadMore).toHaveBeenCalledTimes(1)
})

it('holds a bare spinner before any initial attempt has failed (issue #3429)', () => {
  mockedUseSessions.mockReturnValue({
    data: [],
    isPending: true,
    isLoadingMore: false,
    hasMore: false,
    loadMore: vi.fn(),
    error: null,
    failureCount: 0,
    isRetrying: false,
    refetch: vi.fn(),
  })
  render(<MemoryRouter><HistoryPage /></MemoryRouter>)
  expect(screen.getByText('Loading...')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument()
})

it('offers Retry without a reload once an initial attempt has failed (issue #3429)', () => {
  const refetch = vi.fn()
  mockedUseSessions.mockReturnValue({
    data: [],
    isPending: true,
    isLoadingMore: false,
    hasMore: false,
    loadMore: vi.fn(),
    error: null,
    failureCount: 1,
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
  mockedUseSessions.mockReturnValue({
    data: [],
    isPending: false,
    isLoadingMore: false,
    hasMore: false,
    loadMore: vi.fn(),
    error: new Error('timeout of 10000ms exceeded'),
    failureCount: 4,
    isRetrying: false,
    refetch,
  })
  render(<MemoryRouter><HistoryPage /></MemoryRouter>)
  expect(screen.getByRole('alert')).toHaveTextContent('Failed to load sessions')
  fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
  expect(refetch).toHaveBeenCalledTimes(1)
})

it('keeps the bounded loading state visible during a user-initiated retry (issue #3429)', () => {
  // React Query resets failureCount to 0 when refetch() starts. The page must
  // stay on the bounded retry affordance instead of falling back to the bare
  // splash the user just clicked Retry to escape.
  const refetch = vi.fn()
  mockedUseSessions.mockReturnValue({
    data: [],
    isPending: true,
    isLoadingMore: false,
    hasMore: false,
    loadMore: vi.fn(),
    error: null,
    failureCount: 0,
    isRetrying: true,
    refetch,
  })
  render(<MemoryRouter><HistoryPage /></MemoryRouter>)
  expect(screen.getByRole('status')).toHaveTextContent('Still loading your history')
  expect(screen.queryByText('Loading...')).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
})

it('gives each session-detail link a unique accessible name (issue #3687)', () => {
  mockedUseSessions.mockReturnValue({
    data: [
      { id: 21, started_at: '2024-01-01T10:00:00Z', ended_at: '2024-01-01T10:05:00Z', ladder_path: '6', active_thread: { title: 'Saga', format: 'Comic' }, last_rolled_result: 4, current_die: 6,
      start_die: 6, snapshot_count: 1 },
      { id: 22, started_at: '2024-01-02T11:30:00Z', ended_at: null, ladder_path: null, active_thread: null, last_rolled_result: null, current_die: null, snapshot_count: 0 },
    ],
    isPending: false,
    isLoadingMore: false,
    hasMore: false,
    loadMore: vi.fn(),
    error: null,
  })
  render(<MemoryRouter><HistoryPage /></MemoryRouter>)

  // Acceptance: two sessions rendered together, each reachable by its own
  // accessible name, without depending on the aria-hidden arrow.
  const first = screen.getByRole('link', { name: /^View full session for session 21,/ })
  const second = screen.getByRole('link', { name: /^View full session for session 22,/ })
  expect(first).toHaveAttribute('href', '/sessions/21')
  expect(second).toHaveAttribute('href', '/sessions/22')

  const firstName = first.getAttribute('aria-label') ?? ''
  const secondName = second.getAttribute('aria-label') ?? ''
  expect(firstName).not.toBe(secondName)
  expect(firstName).not.toContain('→')
  expect(secondName).not.toContain('→')

  // The name carries the session start date and time alongside the id.
  const expectedDate = new Date('2024-01-01T10:00:00Z').toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
  })
  expect(firstName).toContain(`started ${expectedDate}`)
  expect(firstName).toMatch(/ at \d{1,2}:\d{2} (AM|PM)/)

  // The visible concise link label stays unchanged.
  expect(first).toHaveTextContent('View full session')
  expect(second).toHaveTextContent('View full session')
})

it('keeps detail-link names unique by session id when the start time is unusable (issue #3687)', () => {
  mockedUseSessions.mockReturnValue({
    data: [
      { id: 4, started_at: 'bad', ended_at: null, ladder_path: null, active_thread: null, last_rolled_result: null, current_die: null, start_die: null, snapshot_count: 0 },
      { id: 8, started_at: null, ended_at: 'bad', ladder_path: null, active_thread: null, last_rolled_result: null, current_die: null, start_die: null, snapshot_count: null },
    ],
    isPending: false,
    isLoadingMore: false,
    hasMore: false,
    loadMore: vi.fn(),
    error: null,
  })
  render(<MemoryRouter><HistoryPage /></MemoryRouter>)

  const first = screen.getByRole('link', { name: 'View full session for session 4' })
  const second = screen.getByRole('link', { name: 'View full session for session 8' })
  expect(first).toHaveAttribute('href', '/sessions/4')
  expect(second).toHaveAttribute('href', '/sessions/8')
  expect(first.getAttribute('aria-label')).not.toBe(second.getAttribute('aria-label'))
})

it('reports the session start die in activity line, not the evolving current die (issue #4243)', () => {
  // The session started with d6 and has a rated activity. Even if the
  // reader's current session uses a different manual die, the history card
  // must always show the session's recorded start die.
  mockedUseSessions.mockReturnValue({
    data: [{
      id: 1018071,
      started_at: '2024-01-01T10:00:00Z',
      ended_at: '2024-01-01T10:45:00Z',
      ladder_path: '6 → 8 → 6',
      active_thread: {
        title: "Superman's Pal, Jimmy Olsen",
        format: 'Comic',
        next_issue_number: '#136',
        issues_read: 1,
        last_rating: 4.0,
      },
      last_rolled_result: 3,
      current_die: 20,
      start_die: 6,
      snapshot_count: 2,
    }],
    isPending: false,
    isLoadingMore: false,
    hasMore: false,
    loadMore: vi.fn(),
    error: null,
  })
  render(<MemoryRouter><HistoryPage /></MemoryRouter>)

  expect(screen.getByText(/rated 4\.0/)).toBeInTheDocument()
  expect(screen.getByText(/Die size d6/)).toBeInTheDocument()
})
