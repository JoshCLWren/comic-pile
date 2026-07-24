import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
import HistoryPage from '../pages/HistoryPage'
import { useSessions } from '../hooks/useSession'

vi.mock('../hooks/useSession', () => ({ useSessions: vi.fn() }))

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

it('renders session cards with optional metadata and duration formats', () => {
  mockedUseSessions.mockReturnValue({ data: [
    { id: 1, started_at: '2024-01-01T10:00:00Z', ended_at: '2024-01-01T10:05:00Z', ladder_path: '6 → 8', active_thread: { title: 'Saga', format: 'Comic' }, last_rolled_result: 4, current_die: 6, snapshot_count: 2 },
    { id: 2, started_at: '2024-01-01T10:00:00Z', ended_at: '2024-01-01T11:00:00Z', ladder_path: null, active_thread: null, snapshot_count: 0 },
    { id: 3, started_at: '2024-01-01T10:00:00Z', ended_at: '2024-01-01T12:30:00Z', ladder_path: '20', active_thread: { title: 'Other', format: 'Manga' }, last_rolled_result: null, current_die: 20, snapshot_count: 1 },
    { id: 4, started_at: 'bad', ended_at: null, ladder_path: null, active_thread: null },
    { id: 5, started_at: '2024-01-01T12:00:00Z', ended_at: '2024-01-01T11:00:00Z', ladder_path: '', active_thread: { title: 'Zero', format: 'Comic' }, last_rolled_result: 0, current_die: 4, snapshot_count: 0 },
    { id: 6, started_at: 'bad', ended_at: 'bad', ladder_path: '6', active_thread: null, snapshot_count: 0 },
    { id: 7, started_at: null, ended_at: 'bad', ladder_path: null, active_thread: null, snapshot_count: null },
    { id: 8, started_at: 'bad', ended_at: 'bad', ladder_path: null, active_thread: null, snapshot_count: null },
  ], isPending: false })
  render(<MemoryRouter><HistoryPage /></MemoryRouter>)
  expect(screen.getByRole('list')).toBeInTheDocument()
  expect(screen.getByText('Dice progression: d6 → d8')).toBeInTheDocument()
  expect(screen.getByText('Duration: 5m')).toBeInTheDocument()
  expect(screen.getByText('Duration: 1h')).toBeInTheDocument()
  expect(screen.getByText('Duration: 2h 30m')).toBeInTheDocument()
  expect(screen.getByText('Comics read: 2')).toBeInTheDocument()
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
    data: [{ id: 1, started_at: '2024-01-01T10:00:00Z', ended_at: null, ladder_path: null, active_thread: null, last_rolled_result: null, current_die: null, snapshot_count: null }],
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
    data: [{ id: 1, started_at: '2024-01-01T10:00:00Z', ended_at: null, ladder_path: null, active_thread: null, last_rolled_result: null, current_die: null, snapshot_count: null }],
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
    data: [{ id: 1, started_at: '2024-01-01T10:00:00Z', ended_at: null, ladder_path: null, active_thread: null, last_rolled_result: null, current_die: null, snapshot_count: null }],
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
