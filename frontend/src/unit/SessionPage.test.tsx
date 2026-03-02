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

beforeEach(() => {
  useSessionDetails.mockReturnValue({
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
  useSessionSnapshots.mockReturnValue({
    data: { snapshots: [{ id: 4, description: 'Before twist', created_at: '2024-05-01T10:20:00Z' }] },
  })
  useRestoreSessionStart.mockReturnValue({ mutate: restoreSpy, isPending: false })
  useUndo.mockReturnValue({ mutate: undoSpy, isPending: false })
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
