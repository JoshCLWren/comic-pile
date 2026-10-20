import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
import ThreadDetailView from '../pages/ThreadDetailView'
import { ToastProvider } from '../contexts/ToastProvider'
import { useUpdateThread } from '../hooks/useThread'
import { threadsApi } from '../services/api-threads'
import { dependenciesApi } from '../services/api-dependencies'
import { issuesApi } from '../services/api-issues'
import { tagsApi } from '../services/api-tags'

/**
 * Regression coverage for #3444: the thread page Edit dialog must defer issue
 * mutations until Save Changes, exactly like the Queue page Edit Series
 * dialog. These tests render the real IssueToggleList inside the dialog with
 * only the API layer mocked.
 */

const routeParams = { id: '1' }

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return {
    ...actual,
    useParams: () => routeParams,
  }
})

vi.mock('../hooks/useThread', async () => {
  const actual = await vi.importActual<typeof import('../hooks/useThread')>('../hooks/useThread')
  return { ...actual, useUpdateThread: vi.fn() }
})

vi.mock('../services/api-threads', () => ({
  threadsApi: { get: vi.fn() },
}))

vi.mock('../services/api-dependencies', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/api-dependencies')>()
  return {
    ...actual,
    dependenciesApi: {
      getIssueDependencies: vi.fn().mockResolvedValue({ incoming: [], outgoing: [] }),
      getConnectedThreads: vi.fn().mockResolvedValue({ connected_threads: [] }),
    },
  }
})

vi.mock('../services/api-issues', () => ({
  issuesApi: {
    list: vi.fn(),
    create: vi.fn(),
    markRead: vi.fn(),
    markUnread: vi.fn(),
    delete: vi.fn(),
    reorder: vi.fn(),
  },
}))

vi.mock('../services/api-tags', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/api-tags')>()
  return {
    ...actual,
    tagsApi: {
      list: vi.fn().mockResolvedValue({ tags: [] }),
      effectiveForIssue: vi.fn().mockResolvedValue({
        target_type: 'Issue',
        target_id: 0,
        direct_tags: [],
        effective_tags: [],
      }),
      effectiveForThread: vi.fn().mockResolvedValue({
        target_type: 'Thread',
        target_id: 1,
        direct_tags: [],
        effective_tags: [],
      }),
      effectiveForPlan: vi.fn().mockResolvedValue({
        target_type: 'ContinuityPlan',
        target_id: 0,
        direct_tags: [],
        effective_tags: [],
      }),
      threadIssuesEffective: vi.fn().mockResolvedValue({ thread_id: 1, issues: [] }),
    },
  }
})

const mockedUseUpdateThread = vi.mocked(useUpdateThread)
const mockedThreadsApiGet = vi.mocked(threadsApi.get)
const mockedIssuesApiList = vi.mocked(issuesApi.list)
const mockedIssuesApiCreate = vi.mocked(issuesApi.create)
const mockedConnectedThreads = vi.mocked(dependenciesApi.getConnectedThreads)
const mockedThreadIssuesTags = vi.mocked(tagsApi.threadIssuesEffective)

beforeEach(() => {
  routeParams.id = '1'
  // SAFETY: the hook mock returns only the fields the component under test reads
  mockedUseUpdateThread.mockReturnValue({
    mutate: vi.fn().mockResolvedValue({}),
    isPending: false,
  } as never)
  mockedThreadsApiGet.mockReset()
  // SAFETY: the stubbed thread supplies only the fields this view reads
  mockedThreadsApiGet.mockResolvedValue({
    id: 1,
    title: 'Saga',
    format: 'Comics',
    issues_remaining: 5,
    queue_position: 1,
    status: 'active',
    total_issues: 10,
    next_unread_issue_number: '3',
    notes: null,
  } as never)
  mockedIssuesApiList.mockReset()
  mockedIssuesApiList.mockResolvedValue({
    issues: [
      { id: 1, thread_id: 1, issue_number: '1', status: 'read', read_at: 'now', created_at: 'now' },
    ],
    next_page_token: null,
    total_count: 1,
    page_size: 100,
  })
  mockedIssuesApiCreate.mockReset()
  // SAFETY: the stubbed create response supplies only the fields this view reads
  mockedIssuesApiCreate.mockResolvedValue({
    issues: [],
    next_page_token: null,
    total_count: 0,
    page_size: 100,
  } as never)
  mockedConnectedThreads.mockReset()
  mockedConnectedThreads.mockResolvedValue({ thread_id: 1, connected_threads: [] })
  mockedThreadIssuesTags.mockReset()
  mockedThreadIssuesTags.mockResolvedValue({ thread_id: 1, issues: [] })
})

function renderPage() {
  return render(
    <MemoryRouter>
      <ToastProvider>
        <ThreadDetailView />
      </ToastProvider>
    </MemoryRouter>,
  )
}

async function openEditDialog() {
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: 'Edit' }))
  const addInput = await screen.findByTestId('issue-add-input')
  return { user, addInput }
}

describe('ThreadDetailView Edit dialog defers issue Add until Save (#3444)', () => {
  it('queues an Add without sending a request and shows it as a pending draft', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())

    const { user, addInput } = await openEditDialog()
    await user.type(addInput, '10-12')
    await user.click(screen.getByTestId('issue-add-button'))

    expect(mockedIssuesApiCreate).not.toHaveBeenCalled()
    expect(await screen.findByTestId('pending-creates')).toHaveTextContent('10-12')
  })

  it('sends the queued Add only when Save Changes is clicked', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())

    const { user, addInput } = await openEditDialog()
    await user.type(addInput, '2')
    await user.click(screen.getByTestId('issue-add-button'))
    expect(mockedIssuesApiCreate).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: 'Save Changes' }))

    await waitFor(() => expect(mockedIssuesApiCreate).toHaveBeenCalledWith(1, '2'))
  })

  it('discards the queued Add when the dialog closes without saving', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())

    const { user, addInput } = await openEditDialog()
    await user.type(addInput, '7-8')
    await user.click(screen.getByTestId('issue-add-button'))
    expect(await screen.findByTestId('pending-creates')).toHaveTextContent('7-8')

    await user.click(screen.getByRole('button', { name: 'Close modal' }))

    expect(mockedIssuesApiCreate).not.toHaveBeenCalled()
    expect(screen.queryByTestId('pending-creates')).not.toBeInTheDocument()
  })
})

/**
 * Regression coverage for #3586 (consolidating #3633): the Edit Series Add
 * box must reject input that is not an issue instead of staging a phantom
 * pending issue chip.
 */
describe('ThreadDetailView Edit dialog rejects invalid issue entries (#3586)', () => {
  it.each([
    ['non-numeric garbage', 'abc'],
    ['a negative issue number', '-3'],
    ['a zero-width space', '\u200b'],
  ])('does not stage a pending chip for %s', async (_label, value) => {
    renderPage()
    await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())

    const { user, addInput } = await openEditDialog()
    await user.type(addInput, value)
    await user.click(screen.getByTestId('issue-add-button'))

    expect(screen.queryByTestId('pending-creates')).not.toBeInTheDocument()
    expect(mockedIssuesApiCreate).not.toHaveBeenCalled()
    expect(screen.getByTestId('issue-add-validation-error')).toBeInTheDocument()
  })

  it('keeps the Save button from persisting a rejected entry', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())

    const { user, addInput } = await openEditDialog()
    await user.type(addInput, 'abc')
    await user.click(screen.getByRole('button', { name: 'Save Changes' }))

    expect(mockedIssuesApiCreate).not.toHaveBeenCalled()
  })

  it('does not stage a pending chip for an entry that names no issue at all', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())

    const { user, addInput } = await openEditDialog()
    await user.type(addInput, ',')
    await user.click(screen.getByTestId('issue-add-button'))

    expect(screen.queryByTestId('pending-creates')).not.toBeInTheDocument()
    expect(mockedIssuesApiCreate).not.toHaveBeenCalled()
    expect(screen.getByTestId('issue-add-validation-error')).toBeInTheDocument()
  })
})
