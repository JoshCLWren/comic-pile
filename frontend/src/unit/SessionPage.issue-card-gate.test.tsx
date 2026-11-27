/**
 * Issue #5904: a legacy session event is a narrative record, not an owned
 * issue identity. The shared covered card may mount only when the owner
 * projection supplies a canonical issue id; title + number must never be
 * turned into a guessed issue, cover or mapping target.
 */
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import SessionPage from '../pages/SessionPage'

const mocks = vi.hoisted(() => ({
  details: vi.fn(),
  snapshots: vi.fn(),
  undo: vi.fn(),
}))

vi.mock('../hooks/useSession', () => ({
  useSessionDetails: mocks.details,
  useSessionSnapshots: mocks.snapshots,
}))
vi.mock('../hooks/useUndo', () => ({ useUndo: mocks.undo }))
vi.mock('../contexts/useToast', () => ({
  useToast: () => ({ showToast: vi.fn() }),
}))
vi.mock('../services/issueCardsApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/issueCardsApi')>()
  return {
    ...actual,
    issueCardsApi: {
      ...actual.issueCardsApi,
      fetchCards: vi.fn(async () => []),
    },
  }
})

interface LegacyEvent {
  id: number
  timestamp: string
  type: string
  thread_title?: string | null
  issue_number?: string | null
  issue_id?: number | null
}

function renderSession(events: LegacyEvent[]) {
  mocks.details.mockReturnValue({
    data: {
      session_id: 12,
      started_at: '2024-05-01T10:00:00Z',
      ended_at: '2024-05-01T11:00:00Z',
      start_die: 6,
      current_die: 8,
      ladder_path: 'd6 → d8',
      narrative_summary: {},
      events,
    },
    isPending: false,
    refetch: vi.fn(),
  })
  mocks.snapshots.mockReturnValue({ data: { snapshots: [] }, refetch: vi.fn() })
  mocks.undo.mockReturnValue({ mutate: vi.fn(), isPending: false })
  return render(
    <MemoryRouter initialEntries={['/sessions/12']}>
      <Routes>
        <Route path="/sessions/:id" element={<SessionPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('session event issue-card gate (#5904)', () => {
  it('keeps title/number-only legacy events text-only', () => {
    renderSession([
      {
        id: 1,
        timestamp: '2024-05-01T10:15:00Z',
        type: 'rate',
        thread_title: 'Saga',
        issue_number: '4',
      },
    ])

    expect(screen.getByText('Saga')).toBeInTheDocument()
    expect(screen.getByText(/· #4/)).toBeInTheDocument()
    expect(document.querySelector('[data-testid^="issue-card-trigger-"]')).toBeNull()
  })

  it('mounts the shared covered card only for a canonical owned issue id', () => {
    renderSession([
      {
        id: 2,
        timestamp: '2024-05-01T10:20:00Z',
        type: 'rate',
        thread_title: 'Saga',
        issue_number: '5',
      },
      {
        id: 3,
        timestamp: '2024-05-01T10:25:00Z',
        type: 'rate',
        thread_title: 'Saga',
        issue_number: '6',
        issue_id: 909,
      },
    ])

    expect(screen.getByTestId('issue-card-trigger-909')).toBeInTheDocument()
    expect(document.querySelectorAll('[data-testid^="issue-card-trigger-"]')).toHaveLength(1)
    expect(screen.queryByTestId('comic-issue-card')).not.toBeInTheDocument()
  })
})
