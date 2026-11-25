import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import HistoryPage from '../pages/HistoryPage'
import type { ActivityItem } from '../services/api-activity'

interface DiscoveredOperation {
  threadId: number
  operation: { id: number; items: unknown[] }
}

const mocks = vi.hoisted(() => ({
  operations: [] as DiscoveredOperation[],
  message: null as string | null,
  undo: vi.fn(async (_threadId: number, _operationId: number): Promise<void> => undefined),
  activity: [] as ActivityItem[],
  list: vi.fn(),
  bulkMarkUnread: vi.fn(),
}))

vi.mock('../hooks/useBulkReadOperations', () => ({
  useBulkReadOperations: () => ({
    operations: mocks.operations,
    message: mocks.message,
    undo: mocks.undo,
  }),
}))

vi.mock('../hooks/useActivity', () => ({
  useActivity: () => ({
    data: mocks.activity,
    isPending: false,
    isLoadingMore: false,
    hasMore: false,
    loadMore: vi.fn(),
    error: null,
    isRetrying: false,
    refetch: vi.fn(),
  }),
}))

vi.mock('../hooks/useIssueCards', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../hooks/useIssueCards')>()
  return { ...actual, useIssueCards: () => ({ data: [] }) }
})

vi.mock('../services/api-issues', () => ({
  issuesApi: { list: mocks.list, bulkMarkUnread: mocks.bulkMarkUnread },
}))

const activityItem: ActivityItem = {
  event_id: 9001,
  type: 'roll',
  timestamp: '2026-11-08T15:42:35.028000Z',
  die_before: 6,
  die_after: null,
  rating: null,
  issue_id: 1121330,
  thread_id: 3153,
  thread_title: 'Saga',
  issue_number: '4',
}

function renderHistory() {
  return render(
    <MemoryRouter>
      <HistoryPage />
    </MemoryRouter>,
  )
}

describe('HistoryPage bulk read undo and restore', () => {
  beforeEach(() => {
    mocks.operations = []
    mocks.message = null
    mocks.undo.mockClear()
    mocks.list.mockReset()
    mocks.bulkMarkUnread.mockReset()
    mocks.activity = [activityItem]
  })

  it('offers undo for a persisted operation and shows its result message', () => {
    mocks.operations = [{ threadId: 42, operation: { id: 7, items: [{}, {}] } }]
    mocks.message = 'Bulk read undone.'

    renderHistory()

    const section = screen.getByTestId('bulk-read-operations')
    expect(section).toHaveTextContent('Operation #7 · 2 issues · series 42')
    expect(screen.getByRole('status')).toHaveTextContent('Bulk read undone.')
    fireEvent.click(screen.getByRole('button', { name: 'Undo' }))
    expect(mocks.undo).toHaveBeenCalledWith(42, 7)
  })

  it('restores read issues and reports the completed restore', async () => {
    mocks.list.mockResolvedValueOnce({ issues: [{ id: 900 }], next_page_token: null })
    mocks.bulkMarkUnread.mockResolvedValueOnce({ id: 3 })

    renderHistory()
    fireEvent.click(screen.getByRole('button', { name: 'Restore unread' }))

    await waitFor(() => expect(mocks.bulkMarkUnread).toHaveBeenCalledWith([900]))
    expect(await screen.findByText('Restored read issues to unread.')).toBeInTheDocument()
    expect(mocks.list).toHaveBeenCalledWith(3153, {
      status: 'read', page_size: 100, page_token: undefined,
    })
  })

  it('reports an empty restore without writing', async () => {
    mocks.list.mockResolvedValueOnce({ issues: [], next_page_token: null })

    renderHistory()
    fireEvent.click(screen.getByRole('button', { name: 'Restore unread' }))

    expect(await screen.findByText('No read issues to restore.')).toBeInTheDocument()
    expect(mocks.bulkMarkUnread).not.toHaveBeenCalled()
  })

  it('reports a failed restore without hiding the failure', async () => {
    mocks.list.mockRejectedValueOnce(new Error('offline'))

    renderHistory()
    fireEvent.click(screen.getByRole('button', { name: 'Restore unread' }))

    expect(await screen.findByText('Failed to restore unread issues.')).toBeInTheDocument()
    expect(mocks.bulkMarkUnread).not.toHaveBeenCalled()
  })
})
