import { render, screen, within } from '@testing-library/react'
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

const showToastSpy = vi.hoisted(() => vi.fn())

vi.mock('../contexts/useToast', () => ({
  useToast: () => ({ toasts: [], showToast: showToastSpy, removeToast: vi.fn() }),
}))

const restoreSpy = vi.fn()
const undoSpy = vi.fn()
const refetchDetailsSpy = vi.fn()
const refetchSnapshotsSpy = vi.fn()
// SAFETY: the module is mocked, so the test supplies the return shape directly
const mockedUseSessionDetails = vi.mocked(useSessionDetails) as any
// SAFETY: the module is mocked, so the test supplies the return shape directly
const mockedUseSessionSnapshots = vi.mocked(useSessionSnapshots) as any
// SAFETY: the module is mocked, so the test supplies the return shape directly
const mockedUseRestoreSessionStart = vi.mocked(useRestoreSessionStart) as any
// SAFETY: the module is mocked, so the test supplies the return shape directly
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
    isPending: false,
    refetch: refetchDetailsSpy,
  })
  mockedUseSessionSnapshots.mockReturnValue({
    data: {
      snapshots: [
        { id: 4, description: 'Before twist', created_at: '2024-05-01T10:20:00Z' },
        { id: 3, description: 'Earlier rating', created_at: '2024-05-01T10:10:00Z' },
      ],
    },
    refetch: refetchSnapshotsSpy,
  })
  mockedUseRestoreSessionStart.mockReturnValue({ mutate: restoreSpy, isPending: false })
  mockedUseUndo.mockReturnValue({ mutate: undoSpy, isPending: false })
  restoreSpy.mockReset()
  undoSpy.mockReset()
  refetchDetailsSpy.mockReset()
  refetchSnapshotsSpy.mockReset()
  showToastSpy.mockClear()
})

it('renders session details and only allows undoing the latest rating', async () => {
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
  expect(screen.getByText('Earlier rating')).toBeInTheDocument()
  expect(screen.getAllByText('History')).toHaveLength(1)
  expect(screen.getAllByRole('button', { name: /undo latest/i })).toHaveLength(1)

  await user.click(screen.getByRole('button', { name: /restore start/i }))
  expect(screen.getByRole('dialog', { name: 'Restore session start?' })).toBeInTheDocument()
  expect(screen.getByText(/replaces your entire current pile/i)).toBeInTheDocument()
  expect(screen.getByText(/reading progress, ratings, and queue order may be reverted/i)).toBeInTheDocument()
  expect(restoreSpy).not.toHaveBeenCalled()

  await user.click(screen.getByRole('button', { name: 'Cancel' }))
  expect(screen.queryByRole('dialog', { name: 'Restore session start?' })).not.toBeInTheDocument()
  expect(restoreSpy).not.toHaveBeenCalled()

  await user.click(screen.getByRole('button', { name: /restore start/i }))
  await user.click(screen.getByRole('button', { name: 'Restore session start' }))
  expect(restoreSpy).toHaveBeenCalledWith(12)
  expect(screen.queryByRole('dialog', { name: 'Restore session start?' })).not.toBeInTheDocument()
  expect(refetchDetailsSpy).toHaveBeenCalledOnce()
  expect(refetchSnapshotsSpy).toHaveBeenCalledOnce()
  expect(showToastSpy).toHaveBeenCalledWith('Session restored to its starting state.', 'success')

  await user.click(screen.getByRole('button', { name: /undo latest/i }))
  expect(undoSpy).toHaveBeenCalledWith({ sessionId: 12, snapshotId: 4 })
  expect(refetchDetailsSpy).toHaveBeenCalledTimes(2)
  expect(refetchSnapshotsSpy).toHaveBeenCalledTimes(2)
  expect(showToastSpy).toHaveBeenCalledWith('Last change undone.', 'success')
})

it('explains how Undo Latest differs from Restore Start instead of leaving two near-identical buttons bare', () => {
  render(<MemoryRouter><SessionPage /></MemoryRouter>)

  const explanation = screen.getByText(/reverses only the newest change/)
  expect(explanation).toHaveTextContent(/Undo Latest/)
  expect(explanation).toHaveTextContent(/stays on the newest snapshot until it has been used once/)
  expect(explanation).toHaveTextContent(/Restore Start/)
  expect(explanation).toHaveTextContent(/rewinds the whole session to the moment it began/)
  expect(explanation).toHaveTextContent(/asks for confirmation first/)
})

it('reports a failed undo instead of leaving the page silent', async () => {
  const user = userEvent.setup()
  undoSpy.mockRejectedValueOnce(new Error('undo failed'))

  render(<MemoryRouter><SessionPage /></MemoryRouter>)
  await user.click(screen.getByRole('button', { name: /undo latest/i }))

  expect(showToastSpy).toHaveBeenCalledWith(
    'Failed to undo the last change. Please try again.',
    'error',
  )
  expect(refetchDetailsSpy).not.toHaveBeenCalled()
  expect(refetchSnapshotsSpy).not.toHaveBeenCalled()
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
  expect(screen.getByText('Abandoned roll')).toBeInTheDocument()
  expect(screen.queryByText('Ended')).not.toBeInTheDocument()
  expect(screen.queryByText('Active')).not.toBeInTheDocument()
  expect(screen.getAllByText('No reading activity was recorded for this roll.').length).toBeGreaterThan(0)
  expect(screen.getByText('No snapshots available.')).toBeInTheDocument()
  expect(screen.getByText('No events to show. No reading activity was recorded for this roll.')).toBeInTheDocument()
})

it('renders fallback labels for sparse summaries and events', () => {
  mockedUseSessionDetails.mockReturnValue({ data: {
    session_id: 14, started_at: '2024-01-01', ended_at: null, start_die: 4, current_die: 4,
    ladder_path: 'd4', narrative_summary: { highlights: [], misses: ['Missed'] },
    events: [{ id: 2, timestamp: '2024-01-01', type: 'shuffle', thread_title: '', rating: 0, result: 0, die: 0, queue_move: '' }],
  }, isPending: false, refetch: refetchDetailsSpy })
  mockedUseSessionSnapshots.mockReturnValue({
    data: { snapshots: [{ id: 5, description: '', created_at: '2024-01-01' }] },
    refetch: refetchSnapshotsSpy,
  })
  render(<MemoryRouter><SessionPage /></MemoryRouter>)
  expect(screen.getAllByText('None').length).toBeGreaterThan(0)
  expect(screen.getByText('Thread unavailable')).toBeInTheDocument()
  expect(screen.getByText('Snapshot')).toBeInTheDocument()
  expect(screen.getByText('Rating 0')).toBeInTheDocument()
  expect(screen.getByText('Selected without rolling')).toBeInTheDocument()
  expect(screen.getByText('d0')).toBeInTheDocument()
})

it('shows session-start snapshots as history instead of rating undo targets', () => {
  mockedUseSessionSnapshots.mockReturnValue({
    data: {
      snapshots: [{ id: 1, description: 'Session start', created_at: '2024-05-01T10:00:00Z' }],
    },
    refetch: refetchSnapshotsSpy,
  })

  render(<MemoryRouter><SessionPage /></MemoryRouter>)

  expect(screen.queryByRole('button', { name: /undo latest/i })).not.toBeInTheDocument()
  expect(screen.getByText('History')).toBeInTheDocument()
})

it('renders pending restore state and optional event metadata', () => {
  mockedUseSessionDetails.mockReturnValue({ data: {
    session_id: 15, started_at: '2024-01-01', ended_at: '2024-01-02', start_die: 4, current_die: 6,
    ladder_path: 'd4 → d6', narrative_summary: undefined,
    events: [{ id: 3, timestamp: '2024-01-01', type: 'move', thread_title: 'Saga', rating: 4, result: 5, die: 6, queue_move: 'front' }],
  }, isPending: false, refetch: refetchDetailsSpy })
  mockedUseSessionSnapshots.mockReturnValue({
    data: { snapshots: [{ id: 6, description: 'Snapshot', created_at: '2024-01-01' }] },
    refetch: refetchSnapshotsSpy,
  })
  mockedUseRestoreSessionStart.mockReturnValue({ mutate: restoreSpy, isPending: true })
  render(<MemoryRouter><SessionPage /></MemoryRouter>)
  expect(screen.getByRole('button', { name: 'Restoring...' })).toBeDisabled()
  expect(screen.getByText('Queue move: front')).toBeInTheDocument()
})

it('renders a complete rate event as one labeled record', () => {
  mockedUseSessionDetails.mockReturnValue({ data: {
    session_id: 16, started_at: '2024-01-01', ended_at: '2024-01-02', start_die: 6, current_die: 8,
    ladder_path: 'd6 → d8', narrative_summary: {},
    events: [{
      id: 7,
      timestamp: '2024-01-01',
      type: 'rate',
      thread_title: 'A Very Long Saga Title That Must Wrap Safely On Mobile',
      issue_number: '5',
      issues_read: 1,
      rating: 4,
      die: 6,
      die_after: 8,
      selection_method: 'dice_roll',
    }],
  }, isPending: false, refetch: refetchDetailsSpy })

  render(<MemoryRouter><SessionPage /></MemoryRouter>)

  const eventDetails = within(screen.getByRole('list', { name: 'Event details' }))
  expect(screen.getByText('Rated')).toBeInTheDocument()
  expect(
    screen.getByText((_text, node) => node?.textContent === 'A Very Long Saga Title That Must Wrap Safely On Mobile · #5'),
  ).toBeInTheDocument()
  expect(eventDetails.getByText('1 issue read')).toBeInTheDocument()
  expect(eventDetails.getByText('Rating 4')).toBeInTheDocument()
  expect(eventDetails.getByText('d6')).toBeInTheDocument()
  expect(eventDetails.getByText('Die after: d8')).toBeInTheDocument()
  expect(eventDetails.getByText('Selected by dice roll')).toBeInTheDocument()
})

it('always pairs a thread title with its issue number in the event timeline', () => {
  mockedUseSessionDetails.mockReturnValue({ data: {
    session_id: 19, started_at: '2024-01-01', ended_at: null, start_die: 6, current_die: 6,
    ladder_path: 'd6', narrative_summary: {},
    events: [
      { id: 20, timestamp: '2024-01-01', type: 'roll', thread_title: 'Saga', issue_number: '44', result: 3, die: 6 },
      { id: 21, timestamp: '2024-01-01', type: 'snooze', thread_title: 'East of West', issue_number: '9' },
    ],
  }, isPending: false, refetch: refetchDetailsSpy })
  mockedUseSessionSnapshots.mockReturnValue({
    data: { snapshots: [{ id: 7, description: 'Snapshot', created_at: '2024-01-01' }] },
    refetch: refetchSnapshotsSpy,
  })

  render(<MemoryRouter><SessionPage /></MemoryRouter>)

  const sagaTitle = screen.getByText((_text, node) => node?.textContent === 'Saga · #44')
  expect(sagaTitle.textContent).toContain('Saga')
  expect(sagaTitle.textContent).toContain('#44')
  const eastTitle = screen.getByText((_text, node) => node?.textContent === 'East of West · #9')
  expect(eastTitle.textContent).toContain('East of West')
  expect(eastTitle.textContent).toContain('#9')
  expect(screen.queryByText('Issue 44')).not.toBeInTheDocument()
})

it('uses human labels and explicit fallback text for sparse events', () => {
  mockedUseSessionDetails.mockReturnValue({ data: {
    session_id: 17, started_at: '2024-01-01', ended_at: null, start_die: 4, current_die: 4,
    ladder_path: 'd4', narrative_summary: {},
    events: [
      { id: 8, timestamp: '2024-01-01', type: 'snooze', thread_title: 'Saga' },
      { id: 9, timestamp: '2024-01-01', type: 'undo', thread_title: null },
    ],
  }, isPending: false, refetch: refetchDetailsSpy })

  render(<MemoryRouter><SessionPage /></MemoryRouter>)

  expect(screen.getByText('Snoozed')).toBeInTheDocument()
  expect(screen.getByText('Restored')).toBeInTheDocument()
  expect(screen.getByText('Thread unavailable')).toBeInTheDocument()
  expect(screen.getAllByText('No additional event details recorded.')).toHaveLength(2)
})

it('describes a roll that never drew a face instead of showing "Rolled 0"', () => {
  mockedUseSessionDetails.mockReturnValue({ data: {
    session_id: 20, started_at: '2024-01-01', ended_at: null, start_die: 6, current_die: 6,
    ladder_path: 'd6', narrative_summary: {},
    events: [
      {
        id: 22,
        timestamp: '2024-01-01',
        type: 'roll',
        thread_title: 'Saga',
        result: 0,
        die: 6,
        selection_method: 'manual',
      },
      {
        id: 23,
        timestamp: '2024-01-01',
        type: 'roll',
        thread_title: 'East of West',
        result: 0,
        die: 8,
        selection_method: 'override',
      },
      {
        id: 24,
        timestamp: '2024-01-01',
        type: 'roll',
        thread_title: 'Blank Books',
        result: 0,
        die: 12,
        selection_method: 'dependency_recovery',
      },
      {
        id: 25,
        timestamp: '2024-01-01',
        type: 'roll',
        thread_title: 'Unrecorded Pick',
        result: 0,
        die: 10,
        selection_method: null,
      },
    ],
  }, isPending: false, refetch: refetchDetailsSpy })

  render(<MemoryRouter><SessionPage /></MemoryRouter>)

  expect(screen.getByText('Selected by manual')).toBeInTheDocument()
  expect(screen.getByText('Selected by override')).toBeInTheDocument()
  expect(screen.getByText('Selected by dependency recovery')).toBeInTheDocument()
  expect(screen.getByText('Selected without rolling')).toBeInTheDocument()
  expect(screen.queryByText('Rolled 0')).not.toBeInTheDocument()
})

it('still reports the drawn face and selection method for a real dice roll', () => {
  mockedUseSessionDetails.mockReturnValue({ data: {
    session_id: 21, started_at: '2024-01-01', ended_at: null, start_die: 20, current_die: 20,
    ladder_path: 'd20', narrative_summary: {},
    events: [
      {
        id: 26,
        timestamp: '2024-01-01',
        type: 'roll',
        thread_title: 'Saga',
        result: 13,
        die: 20,
        selection_method: 'momentum',
      },
    ],
  }, isPending: false, refetch: refetchDetailsSpy })

  render(<MemoryRouter><SessionPage /></MemoryRouter>)

  const eventDetails = within(screen.getByRole('list', { name: 'Event details' }))
  expect(eventDetails.getByText('Rolled 13')).toBeInTheDocument()
  expect(eventDetails.getByText('Selected by momentum')).toBeInTheDocument()
})

it('renders reader-language event descriptions instead of the placeholder', () => {
  mockedUseSessionDetails.mockReturnValue({ data: {
    session_id: 18, started_at: '2024-01-01', ended_at: null, start_die: 6, current_die: 6,
    ladder_path: 'd6', narrative_summary: {},
    events: [
      { id: 10, timestamp: '2024-01-01', type: 'snooze', thread_title: 'Wolverine', description: 'Snoozed Wolverine' },
      { id: 11, timestamp: '2024-01-02', type: 'skip', thread_title: null, description: 'Skipped thread' },
    ],
  }, isPending: false, refetch: refetchDetailsSpy })

  render(<MemoryRouter><SessionPage /></MemoryRouter>)

  expect(screen.getByText('Snoozed Wolverine')).toBeInTheDocument()
  expect(screen.getByText('Skipped thread')).toBeInTheDocument()
  expect(screen.queryByText('No additional event details recorded.')).not.toBeInTheDocument()
})

// #3300: an undo/restore description that only repeats the card's own label made
// two genuinely different actions read as the same card. The repeated segment
// goes; the trailing detail the backend appended stays.
it('drops a restore description that only repeats the card label but keeps its extras', () => {
  mockedUseSessionDetails.mockReturnValue({ data: {
    session_id: 22, started_at: '2024-01-01', ended_at: null, start_die: 6, current_die: 6,
    ladder_path: 'd6', narrative_summary: {},
    events: [
      { id: 30, timestamp: '2024-01-01T13:04:03Z', type: 'undo', thread_title: 'Saga', description: 'Restored Saga' },
      {
        id: 31,
        timestamp: '2024-01-01T13:04:47Z',
        type: 'restore',
        thread_title: null,
        issue_number: '5',
        description: 'Restored thread · #5',
      },
    ],
  }, isPending: false, refetch: refetchDetailsSpy })

  render(<MemoryRouter><SessionPage /></MemoryRouter>)

  expect(screen.queryByText('Restored Saga')).not.toBeInTheDocument()
  expect(screen.queryByText('Restored thread · #5')).not.toBeInTheDocument()
  expect(screen.getByText('#5')).toBeInTheDocument()
  expect(screen.getByText('Thread unavailable')).toBeInTheDocument()
  expect(screen.queryByText('No additional event details recorded.')).not.toBeInTheDocument()
})

// #3300: minute-precision rendering collapsed distinct events into one block of
// identical timestamps, which is what made the reported pairs look duplicated.
it('separates same-minute timeline events with second precision', () => {
  mockedUseSessionDetails.mockReturnValue({ data: {
    session_id: 23, started_at: '2024-01-01', ended_at: null, start_die: 20, current_die: 20,
    ladder_path: 'd20', narrative_summary: {},
    events: [
      { id: 32, timestamp: '2024-01-01T13:04:03Z', type: 'roll', thread_title: 'Flash', result: 20, die: 20, selection_method: 'random' },
      { id: 33, timestamp: '2024-01-01T13:04:47Z', type: 'roll', thread_title: 'Flash', result: 20, die: 20, selection_method: 'random' },
    ],
  }, isPending: false, refetch: refetchDetailsSpy })

  render(<MemoryRouter><SessionPage /></MemoryRouter>)

  const timestamps = screen.getAllByText(/\d{1,2}:\d{2}:\d{2}/)
  expect(timestamps).toHaveLength(2)
  expect(new Set(timestamps.map((node) => node.textContent)).size).toBe(2)
})
