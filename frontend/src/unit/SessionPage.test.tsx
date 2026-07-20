import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
import SessionPage from '../pages/SessionPage'
import {
  useRestoreSessionStart,
  useSessionDetails,
  useSessionSnapshots,
} from '../hooks/useSession'
import { useUndo } from '../hooks/useUndo'

vi.mock('../hooks/useSession', () => ({
  useSessionDetails: vi.fn(),
  useSessionSnapshots: vi.fn(),
  useRestoreSessionStart: vi.fn(),
}))

vi.mock('../hooks/useUndo', () => ({
  useUndo: vi.fn(),
}))

const restoreSpy = vi.fn()
const undoSpy = vi.fn()
const mockedUseSessionDetails = vi.mocked(useSessionDetails) as any
const mockedUseSessionSnapshots = vi.mocked(useSessionSnapshots) as any
const mockedUseRestoreSessionStart = vi.mocked(useRestoreSessionStart) as any
const mockedUseUndo = vi.mocked(useUndo) as any

beforeEach(() => {
  mockedUseSessionDetails.mockReturnValue({
    data: {
      session_id: 12,
      started_at: '2024-05-01T10:00:00Z',
      ended_at: '2024-05-01T11:00:00Z',
      start_die: 6,
      current_die: 8,
      ladder_path: 'd6 → d8',
      narrative_summary: { highlights: ['Big moment'] },
      events: [
        { id: 1, timestamp: '2024-05-01T10:15:00Z', type: 'roll', thread_title: 'Saga', result: 3, die: 6 },
      ],
    },
    isLoading: false,
  })
  mockedUseSessionSnapshots.mockReturnValue({
    data: { snapshots: [{ id: 4, description: 'Before twist', created_at: '2024-05-01T10:20:00Z' }] },
  })
  mockedUseRestoreSessionStart.mockReturnValue({ mutate: restoreSpy, isPending: false })
  mockedUseUndo.mockReturnValue({ mutate: undoSpy, isPending: false })
  restoreSpy.mockReset()
  undoSpy.mockReset()
})

it('renders session details and triggers restore actions', async () => {
  const user = userEvent.setup()
  render(
    <MemoryRouter initialEntries={["/sessions/12"]}>
      <Routes>
        <Route path="/sessions/:id" element={<SessionPage />} />
      </Routes>
    </MemoryRouter>
  )

  expect(screen.getByText('Session Details')).toBeInTheDocument()
  expect(screen.getByText('Before twist')).toBeInTheDocument()

  await user.click(screen.getByRole('button', { name: /restore start/i }))
  expect(restoreSpy).toHaveBeenCalledWith(12)

  await user.click(screen.getByRole('button', { name: /undo/i }))
  expect(undoSpy).toHaveBeenCalledWith({ sessionId: 12, snapshotId: 4 })
})

it('renders loading, missing, empty, and active session branches', () => {
  mockedUseSessionDetails.mockReturnValue({ data: undefined, isPending: true })
  const { rerender } = render(<MemoryRouter><SessionPage /></MemoryRouter>)
  expect(screen.getByRole('status')).toBeInTheDocument()
  mockedUseSessionDetails.mockReturnValue({ data: undefined, isPending: false })
  rerender(<MemoryRouter><SessionPage /></MemoryRouter>)
  expect(screen.getByText('Session not found')).toBeInTheDocument()

  mockedUseSessionDetails.mockReturnValue({ data: {
    session_id: 13, started_at: '2024-01-01', ended_at: null, start_die: 4, current_die: 4,
    ladder_path: 'd4', narrative_summary: { highlights: [], misses: [] }, events: [],
  }, isPending: false })
  mockedUseSessionSnapshots.mockReturnValue({ data: undefined })
  rerender(<MemoryRouter><SessionPage /></MemoryRouter>)
  expect(screen.getByText('Active')).toBeInTheDocument()
  expect(screen.getByText('No snapshots available.')).toBeInTheDocument()
  expect(screen.getByText('No events recorded.')).toBeInTheDocument()
})

it('renders fallback labels for sparse summaries and events', () => {
  mockedUseSessionDetails.mockReturnValue({ data: {
    session_id: 14, started_at: '2024-01-01', ended_at: null, start_die: 4, current_die: 4,
    ladder_path: 'd4', narrative_summary: { highlights: [], misses: ['Missed'] },
    events: [{ id: 2, timestamp: '2024-01-01', type: 'shuffle', thread_title: '', rating: 0, result: 0, die: 0, queue_move: '' }],
  }, isPending: false })
  mockedUseSessionSnapshots.mockReturnValue({ data: { snapshots: [{ id: 5, description: '', created_at: '2024-01-01' }] } })
  render(<MemoryRouter><SessionPage /></MemoryRouter>)
  expect(screen.getAllByText('None').length).toBeGreaterThan(0)
  expect(screen.getByText('Thread')).toBeInTheDocument()
  expect(screen.getByText('Snapshot')).toBeInTheDocument()
})

it('renders pending restore state and optional event metadata', () => {
  mockedUseSessionDetails.mockReturnValue({ data: {
    session_id: 15, started_at: '2024-01-01', ended_at: '2024-01-02', start_die: 4, current_die: 6,
    ladder_path: 'd4 → d6', narrative_summary: undefined,
    events: [{ id: 3, timestamp: '2024-01-01', type: 'move', thread_title: 'Saga', rating: 4, result: 5, die: 6, queue_move: 'front' }],
  }, isPending: false })
  mockedUseSessionSnapshots.mockReturnValue({ data: { snapshots: [{ id: 6, description: 'Snapshot', created_at: '2024-01-01' }] } })
  mockedUseRestoreSessionStart.mockReturnValue({ mutate: restoreSpy, isPending: true })
  render(<MemoryRouter><SessionPage /></MemoryRouter>)
  expect(screen.getByRole('button', { name: 'Restoring...' })).toBeDisabled()
  expect(screen.getByText('Queue move: front')).toBeInTheDocument()
})
