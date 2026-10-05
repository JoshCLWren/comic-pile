import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ThreadDetailView from '../pages/ThreadDetailView'
import { ToastProvider } from '../contexts/ToastProvider'
import { queryKeys } from '../query/queryKeys'
import { queryClient } from '../query/queryClient'
import { threadsApi } from '../services/api-threads'
import { dependenciesApi, issueDependenciesApi } from '../services/api-dependencies'
import { dependencyGroupsApi } from '../services/api-dependency-groups'
import { issuesApi } from '../services/api-issues'
import type { Issue, Thread } from '../types'

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useParams: () => ({ id: '1' }), useLocation: () => ({ state: undefined }) }
})
vi.mock('../services/api-threads', () => ({ threadsApi: { get: vi.fn() } }))
vi.mock('../services/api-issues', () => ({
  issuesApi: {
    list: vi.fn(),
    get: vi.fn(),
    create: vi.fn(),
    markRead: vi.fn(),
    markUnread: vi.fn(),
    delete: vi.fn(),
    reorder: vi.fn(),
  },
}))
vi.mock('../services/api-dependencies', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/api-dependencies')>()
  return {
    ...actual,
    dependenciesApi: { getConnectedThreads: vi.fn() },
    issueDependenciesApi: { listForThread: vi.fn() },
  }
})
vi.mock('../services/api-dependency-groups', () => ({
  dependencyGroupsApi: { listForThreads: vi.fn() },
}))

const mockedThreadsApiGet = vi.mocked(threadsApi.get)
const mockedIssuesApiList = vi.mocked(issuesApi.list)
const mockedIssuesApiGet = vi.mocked(issuesApi.get)
const mockedMarkRead = vi.mocked(issuesApi.markRead)
const mockedMarkUnread = vi.mocked(issuesApi.markUnread)

const readIssue: Issue = {
  id: 1,
  thread_id: 1,
  issue_number: '1',
  status: 'read',
  read_at: '2026-10-01T00:00:00Z',
  created_at: '2026-10-01T00:00:00Z',
}

const unreadIssue: Issue = {
  ...readIssue,
  status: 'unread',
  read_at: null,
}

const completedThread: Thread = {
  id: 1,
  title: 'Saga',
  format: 'Comics',
  issues_remaining: 0,
  total_issues: 1,
  next_unread_issue_id: null,
  next_unread_issue_number: null,
  queue_position: 1,
  status: 'completed',
  reading_progress: 'completed',
  notes: null,
  is_blocked: false,
  blocking_reasons: [],
  last_activity_at: null,
  last_rating: null,
  is_test: false,
  created_at: '2026-10-01T00:00:00Z',
}

const activeThread: Thread = {
  ...completedThread,
  issues_remaining: 1,
  next_unread_issue_id: 1,
  next_unread_issue_number: '1',
  status: 'active',
  reading_progress: 'in_progress',
}

/** Mutable server row so every read reflects the post-mutation truth. */
let serverThread: Thread
let serverIssue: Issue

function renderPage() {
  return render(
    <MemoryRouter>
      <ToastProvider>
        <ThreadDetailView />
      </ToastProvider>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  serverThread = completedThread
  serverIssue = readIssue

  mockedThreadsApiGet.mockImplementation(async () => serverThread)
  mockedIssuesApiList.mockImplementation(async () => ({
    issues: [serverIssue],
    next_page_token: null,
    total_count: 1,
    page_size: 100,
  }))
  mockedIssuesApiGet.mockImplementation(async () => serverIssue)
  vi.mocked(dependenciesApi.getConnectedThreads).mockResolvedValue({
    thread_id: 1,
    connected_threads: [],
  })
  vi.mocked(issueDependenciesApi.listForThread).mockResolvedValue({ thread_id: 1, issues: [] })
  vi.mocked(dependencyGroupsApi.listForThreads).mockResolvedValue({})
})

describe('ThreadDetailView issue toggle thread-status sync (#3113)', () => {
  it('reactivates STATUS when an inline mark-unread un-completes the thread', async () => {
    mockedMarkUnread.mockImplementation(async () => {
      serverThread = activeThread
      serverIssue = unreadIssue
    })

    renderPage()
    await waitFor(() => expect(screen.getByText('completed')).toBeInTheDocument())

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Expand' }))
    await waitFor(() => expect(screen.getByText('#1')).toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: 'Mark unread' }))

    // The progress counters already refreshed before the fix, which is why the
    // stale STATUS survived; both must now move together.
    await waitFor(() => expect(screen.getByText('0 of 1 issues read')).toBeInTheDocument())
    await waitFor(() => expect(screen.getByText('active')).toBeInTheDocument())
    expect(screen.queryByText('completed')).not.toBeInTheDocument()
    expect(queryClient.getQueryData(queryKeys.thread.detail(1))).toMatchObject({
      status: 'active',
      reading_progress: 'in_progress',
      issues_remaining: 1,
    })
  })

  it('completes STATUS when an inline mark-read finishes the thread', async () => {
    serverThread = activeThread
    serverIssue = unreadIssue
    mockedMarkRead.mockImplementation(async () => {
      serverThread = completedThread
      serverIssue = readIssue
    })

    renderPage()
    await waitFor(() => expect(screen.getByText('active')).toBeInTheDocument())

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Expand' }))
    await waitFor(() => expect(screen.getByText('#1')).toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: 'Mark read' }))

    await waitFor(() => expect(screen.getByText('1 of 1 issues read')).toBeInTheDocument())
    await waitFor(() => expect(screen.getByText('completed')).toBeInTheDocument())
    expect(screen.queryByText('active')).not.toBeInTheDocument()
  })

  it('refetches the thread after an edit-modal issue pill toggle', async () => {
    serverThread = activeThread
    serverIssue = unreadIssue
    mockedMarkRead.mockImplementation(async () => {
      serverThread = completedThread
      serverIssue = readIssue
    })

    renderPage()
    await waitFor(() => expect(screen.getByText('active')).toBeInTheDocument())
    const readsBeforeToggle = mockedThreadsApiGet.mock.calls.length

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Edit' }))
    await waitFor(() => expect(screen.getByTestId('issue-toggle-1')).toBeInTheDocument())
    await user.click(screen.getByTestId('issue-toggle-1'))

    await waitFor(() =>
      expect(mockedThreadsApiGet.mock.calls.length).toBeGreaterThan(readsBeforeToggle),
    )
    await waitFor(() => expect(screen.getByText('completed')).toBeInTheDocument())
    expect(queryClient.getQueryData(queryKeys.thread.detail(1))).toMatchObject({
      status: 'completed',
      issues_remaining: 0,
    })
  })
})
