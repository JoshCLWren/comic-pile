import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ThreadDetailView from '../pages/ThreadDetailView'
import { ToastProvider } from '../contexts/ToastProvider'
import { useUpdateThread } from '../hooks/useThread'
import { threadsApi } from '../services/api-threads'
import { dependenciesApi } from '../services/api-dependencies'
import { issuesApi } from '../services/api-issues'
import { tagsApi } from '../services/api-tags'

/**
 * Regression coverage for #4356 / MQA-QUEUE-008: closing a dirty Edit Series
 * draft with the dialog close control (×, Escape, backdrop) must ask whether
 * to discard; closing an unchanged draft asks nothing. The queue page dialog
 * already implements this (QueueModals); the thread detail page dialog must
 * match it.
 *
 * These tests render the real IssueToggleList inside the dialog with only the
 * API layer mocked.
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

const mutateMock = vi.fn().mockResolvedValue({})

beforeEach(() => {
  routeParams.id = '1'
  mutateMock.mockClear()
  // SAFETY: the hook mock returns only the fields the component under test reads
  mockedUseUpdateThread.mockReturnValue({
    mutate: mutateMock,
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
    notes: 'original note',
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
  expect(await screen.findByLabelText('Notes')).toBeVisible()
  return { user }
}

describe('Thread detail Edit Series discard confirmation (#4356)', () => {
  it('closes an unchanged draft without prompting', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())

    const { user } = await openEditDialog()
    await user.click(screen.getByRole('button', { name: 'Close modal' }))

    expect(screen.queryByRole('dialog', { name: 'Discard changes?' })).not.toBeInTheDocument()
    expect(screen.queryByRole('dialog', { name: 'Edit Series' })).not.toBeInTheDocument()
    expect(mutateMock).not.toHaveBeenCalled()
  })

  it.each([
    ['Title', 'Saga', 'Saga updated'],
    ['Notes', 'original note', 'original note updated'],
  ])(
    'prompts when a dirty %s draft is closed with the dialog close control and keeps the draft when editing continues',
    async (_field, initialValue, expectedValue) => {
      renderPage()
      await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())

      const { user } = await openEditDialog()
      await user.type(screen.getByDisplayValue(initialValue), ' updated')
      await user.click(screen.getByRole('button', { name: 'Close modal' }))

      const prompt = screen.getByRole('dialog', { name: 'Discard changes?' })
      expect(prompt).toBeInTheDocument()
      expect(mutateMock).not.toHaveBeenCalled()

      await user.click(within(prompt).getByRole('button', { name: 'Keep editing' }))
      expect(screen.queryByRole('dialog', { name: 'Discard changes?' })).not.toBeInTheDocument()
      expect(screen.getByRole('dialog', { name: 'Edit Series' })).toBeInTheDocument()
      expect(screen.getByDisplayValue(expectedValue)).toHaveValue(expectedValue)
      expect(mutateMock).not.toHaveBeenCalled()
    },
  )

  it('prompts when a dirty Notes draft is closed with Escape and discards only after confirmation', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())

    const { user } = await openEditDialog()
    await user.type(screen.getByLabelText('Notes'), ' updated')
    await user.keyboard('{Escape}')

    const prompt = screen.getByRole('dialog', { name: 'Discard changes?' })
    expect(prompt).toBeInTheDocument()

    await user.click(within(prompt).getByRole('button', { name: 'Discard changes' }))
    expect(screen.queryByRole('dialog', { name: 'Edit Series' })).not.toBeInTheDocument()
    expect(mutateMock).not.toHaveBeenCalled()
  })

  it('warns for a queued issue edit alone and discards only after confirmation', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())

    const { user } = await openEditDialog()
    const addInput = await screen.findByTestId('issue-add-input')
    await user.type(addInput, '7-8')
    await user.click(screen.getByTestId('issue-add-button'))
    expect(await screen.findByTestId('pending-creates')).toHaveTextContent('7-8')
    expect(mockedIssuesApiCreate).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: 'Close modal' }))
    const prompt = screen.getByRole('dialog', { name: 'Discard changes?' })
    expect(prompt).toBeInTheDocument()

    await user.click(within(prompt).getByRole('button', { name: 'Discard changes' }))
    expect(screen.queryByRole('dialog', { name: 'Edit Series' })).not.toBeInTheDocument()
    expect(mockedIssuesApiCreate).not.toHaveBeenCalled()
    expect(mutateMock).not.toHaveBeenCalled()
  })
})
