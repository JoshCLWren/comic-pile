import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'
import ThreadDetailView from '../pages/ThreadDetailView'
import { useUpdateThread } from '../hooks/useThread'
import { threadsApi } from '../services/api'
import { issuesApi } from '../services/api-issues'

const routeParams = { id: '1' }

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => vi.fn(), useParams: () => routeParams }
})
vi.mock('../hooks/useThread', () => ({ useUpdateThread: vi.fn() }))
vi.mock('../services/api', () => {
  const client = { get: vi.fn() }
  return {
    default: client,
    threadsApi: { get: vi.fn() },
    dependenciesApi: { getIssueDependencies: vi.fn().mockResolvedValue({ incoming: [], outgoing: [] }) },
  }
})
vi.mock('../services/api-issues', () => ({ issuesApi: { list: vi.fn() } }))

const mockedUseUpdateThread = vi.mocked(useUpdateThread)
const mockedThreadsApiGet = vi.mocked(threadsApi.get)
const mockedIssuesApiList = vi.mocked(issuesApi.list)

function threadResult(id: number) {
  return {
    id,
    title: id === 1 ? 'Saga' : 'Monstress',
    format: 'Comics',
    issues_remaining: 1,
    queue_position: id,
    status: 'active',
    total_issues: 1,
    next_unread_issue_number: '1',
    notes: null,
  } as never
}

function issueResult(threadId: number) {
  return {
    issues: [{
      id: threadId,
      thread_id: threadId,
      issue_number: threadId === 1 ? 'Saga 1' : 'Monstress 1',
      status: 'unread',
      read_at: null,
      created_at: 'now',
    }],
    next_page_token: null,
    total_count: 1,
    page_size: 100,
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

beforeEach(() => {
  routeParams.id = '1'
  mockedUseUpdateThread.mockReturnValue({ mutate: vi.fn(), isPending: false } as never)
  mockedThreadsApiGet.mockImplementation(async (id: number) => threadResult(id))
  mockedIssuesApiList.mockImplementation(async (threadId: number) => issueResult(threadId))
})

it('clears loaded issues and fetches the new thread after a route change', async () => {
  const user = userEvent.setup()
  const view = render(<ThreadDetailView />)

  await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())
  await user.click(screen.getByRole('button', { name: 'Expand' }))
  await waitFor(() => expect(screen.getByText('#Saga 1')).toBeInTheDocument())

  routeParams.id = '2'
  view.rerender(<ThreadDetailView />)

  await waitFor(() => expect(screen.getByText('Monstress')).toBeInTheDocument())
  expect(screen.queryByText('#Saga 1')).not.toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Expand' }))
  await waitFor(() => expect(screen.getByText('#Monstress 1')).toBeInTheDocument())

  expect(mockedIssuesApiList).toHaveBeenNthCalledWith(1, 1, { page_size: 100 })
  expect(mockedIssuesApiList).toHaveBeenNthCalledWith(2, 2, { page_size: 100 })
})

it('ignores stale successful and failed thread requests after navigation', async () => {
  const firstRequest = deferred<ReturnType<typeof threadResult>>()
  mockedThreadsApiGet.mockImplementation((id: number) => (
    id === 1 ? firstRequest.promise : Promise.resolve(threadResult(id))
  ))
  const view = render(<ThreadDetailView />)

  routeParams.id = '2'
  view.rerender(<ThreadDetailView />)
  await waitFor(() => expect(screen.getByText('Monstress')).toBeInTheDocument())

  firstRequest.resolve(threadResult(1))
  await waitFor(() => expect(screen.queryByText('Saga')).not.toBeInTheDocument())

  const rejectedRequest = deferred<ReturnType<typeof threadResult>>()
  mockedThreadsApiGet.mockImplementation((id: number) => (
    id === 1 ? rejectedRequest.promise : Promise.resolve(threadResult(id))
  ))
  routeParams.id = '1'
  view.rerender(<ThreadDetailView />)
  routeParams.id = '2'
  view.rerender(<ThreadDetailView />)
  await waitFor(() => expect(screen.getByText('Monstress')).toBeInTheDocument())

  rejectedRequest.reject(new Error('stale failure'))
  await waitFor(() => expect(screen.queryByText('stale failure')).not.toBeInTheDocument())
})

it('ignores stale successful and failed issue requests after navigation', async () => {
  const user = userEvent.setup()
  const firstIssues = deferred<ReturnType<typeof issueResult>>()
  mockedIssuesApiList.mockImplementation((threadId: number) => (
    threadId === 1 ? firstIssues.promise : Promise.resolve(issueResult(threadId))
  ))
  const view = render(<ThreadDetailView />)

  await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())
  await user.click(screen.getByRole('button', { name: 'Expand' }))
  routeParams.id = '2'
  view.rerender(<ThreadDetailView />)
  await waitFor(() => expect(screen.getByText('Monstress')).toBeInTheDocument())

  firstIssues.resolve(issueResult(1))
  await waitFor(() => expect(screen.queryByText('#Saga 1')).not.toBeInTheDocument())

  const rejectedIssues = deferred<ReturnType<typeof issueResult>>()
  mockedIssuesApiList.mockImplementation((threadId: number) => (
    threadId === 1 ? rejectedIssues.promise : Promise.resolve(issueResult(threadId))
  ))
  routeParams.id = '1'
  view.rerender(<ThreadDetailView />)
  await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())
  await user.click(screen.getByRole('button', { name: 'Expand' }))
  routeParams.id = '2'
  view.rerender(<ThreadDetailView />)
  await waitFor(() => expect(screen.getByText('Monstress')).toBeInTheDocument())

  rejectedIssues.reject(new Error('stale issue failure'))
  await waitFor(() => expect(screen.queryByText('Failed to load issues')).not.toBeInTheDocument())
})

it('handles a route without a thread id without making requests', async () => {
  routeParams.id = ''
  render(<ThreadDetailView />)

  await waitFor(() => expect(screen.getByText('Thread not found')).toBeInTheDocument())
  expect(mockedThreadsApiGet).not.toHaveBeenCalled()
  expect(mockedIssuesApiList).not.toHaveBeenCalled()
})
