import { forwardRef, useImperativeHandle } from 'react'
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
import type { IssueToggleListHandle } from '../pages/QueuePage/IssueToggleList'

/**
 * Regression coverage for #3444: the thread page Edit dialog flushes deferred
 * issue mutations through the IssueToggleList imperative handle before saving
 * the thread, mirroring the Queue page Edit Series dialog (#3309).
 *
 * IssueToggleList is replaced with a recording mock so the flush ordering and
 * error handling of ThreadDetailView itself can be asserted directly.
 */

const order: string[] = []
let deferredSeen: boolean | null = null
let pendingAvailable = true
let flushError: Error | null = null

vi.mock('../pages/QueuePage/IssueToggleList', () => ({
  IssueToggleList: forwardRef<IssueToggleListHandle, { deferred?: boolean }>((props, ref) => {
    deferredSeen = props.deferred === true
    useImperativeHandle(ref, () => ({
      flush: async () => {
        order.push('flush')
        await Promise.resolve()
        if (flushError) {
          throw flushError
        }
      },
      hasPendingMutations: () => pendingAvailable,
    }))
    return <div data-testid="issue-toggle-list" />
  }),
}))

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

vi.mock('../services/api-issues', () => ({ issuesApi: { list: vi.fn() } }))

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

const mutateMock = vi.fn(() => {
  order.push('mutate')
  return Promise.resolve({})
})

const mockedUseUpdateThread = vi.mocked(useUpdateThread)
const mockedThreadsApiGet = vi.mocked(threadsApi.get)
const mockedIssuesApiList = vi.mocked(issuesApi.list)
const mockedConnectedThreads = vi.mocked(dependenciesApi.getConnectedThreads)
const mockedThreadIssuesTags = vi.mocked(tagsApi.threadIssuesEffective)

beforeEach(() => {
  order.length = 0
  deferredSeen = null
  pendingAvailable = true
  flushError = null
  mutateMock.mockClear()
  routeParams.id = '1'
  // SAFETY: the hook mock returns only the fields the component under test reads
  mockedUseUpdateThread.mockReturnValue({ mutate: mutateMock, isPending: false } as never)
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
  mockedIssuesApiList.mockResolvedValue({ issues: [], next_page_token: null, total_count: 0, page_size: 100 })
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
  await screen.findByTestId('issue-toggle-list')
  return user
}

describe('ThreadDetailView Edit dialog deferred flush (#3444)', () => {
  it('renders IssueToggleList in deferred mode inside the Edit dialog', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())

    await openEditDialog()

    expect(screen.getByTestId('issue-toggle-list')).toBeInTheDocument()
    expect(deferredSeen).toBe(true)
  })

  it('flushes pending issue mutations before saving the thread', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())

    const user = await openEditDialog()
    await user.click(screen.getByRole('button', { name: 'Save Changes' }))

    await waitFor(() => expect(mutateMock).toHaveBeenCalled())
    expect(order).toEqual(['flush', 'mutate'])
  })

  it('skips the flush when there are no pending issue mutations', async () => {
    pendingAvailable = false
    renderPage()
    await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())

    const user = await openEditDialog()
    await user.click(screen.getByRole('button', { name: 'Save Changes' }))

    await waitFor(() => expect(mutateMock).toHaveBeenCalled())
    expect(order).toEqual(['mutate'])
  })

  it('reports a flush failure and skips the thread update', async () => {
    flushError = new Error('Flush failed')
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    renderPage()
    await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())

    const user = await openEditDialog()
    await user.click(screen.getByRole('button', { name: 'Save Changes' }))

    await waitFor(() => {
      expect(consoleSpy).toHaveBeenCalledWith(
        'Failed to update thread or flush issues:',
        expect.any(Error),
      )
    })
    expect(mutateMock).not.toHaveBeenCalled()
    consoleSpy.mockRestore()
  })
})
