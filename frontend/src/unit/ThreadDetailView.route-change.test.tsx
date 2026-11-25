import { act, render, screen, waitFor } from './testingLibrary'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
import ThreadDetailView from '../pages/ThreadDetailView'
import { ToastProvider } from '../contexts/ToastProvider'
import { queryKeys } from '../query/queryKeys'
import { queryClient } from '../query/queryClient'
import { useUpdateThread } from '../hooks/useThread'
import { threadsApi } from '../services/api-threads'
import { issuesApi } from '../services/api-issues'
import type { IssueListResponse, Thread } from '../types'
import { injectModuleDoubles } from './injectModuleDoubles'
import { NavigationSpy } from './routerTestHarness'

const navigateSpy = vi.fn()
await injectModuleDoubles(await import('../hooks/useThread'), async () => {
  const actual = await vi.importActual<typeof import('../hooks/useThread')>('../hooks/useThread')
  return { ...actual, useUpdateThread: vi.fn() }
})
await injectModuleDoubles(await import('../services/api-threads'), () => ({
  threadsApi: { get: vi.fn() },
}))
await injectModuleDoubles(await import('../services/api-dependencies'), () => ({
  dependenciesApi: {
    getIssueDependencies: vi.fn().mockResolvedValue({ incoming: [], outgoing: [] }),
    getConnectedThreads: vi.fn().mockResolvedValue({ connected_threads: [] }),
  },
}))
await injectModuleDoubles(await import('../services/api-issues'), () => ({ issuesApi: { list: vi.fn() } }))
await injectModuleDoubles(await import('../services/api-tags'), async (importOriginal) => {
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

function threadResult(id: number): Thread {
  // SAFETY: the thread fixture supplies only the fields the view reads on this route
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
  } as Thread
}

function issueResult(threadId: number): IssueListResponse {
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
  navigateSpy.mockReset()
  // SAFETY: the hook mock returns only the fields the component under test reads
  mockedUseUpdateThread.mockReturnValue({ mutate: vi.fn(), isPending: false } as never)
  mockedThreadsApiGet.mockReset()
  mockedThreadsApiGet.mockImplementation(async (id: number) => threadResult(id))
  mockedIssuesApiList.mockReset()
  mockedIssuesApiList.mockImplementation(async (threadId: number) => issueResult(threadId))
})

function threadDetailHarness(threadId = '1') {
  const initialPath = threadId ? `/thread/${threadId}` : '/thread'
  return (
    <MemoryRouter initialEntries={[initialPath]}>
      <NavigationSpy navigate={navigateSpy} />
      <ToastProvider>
        <Routes>
          <Route path="/thread/:id" element={<ThreadDetailView />} />
          <Route path="/thread" element={<ThreadDetailView />} />
        </Routes>
      </ToastProvider>
    </MemoryRouter>
  )
}

function renderView(threadId = '1') {
  return render(threadDetailHarness(threadId))
}

function navigateToThread(threadId: string) {
  act(() => {
    navigateSpy(`/thread/${threadId}`)
  })
}

it('clears loaded issues and fetches the new thread after a route change', async () => {
  const user = userEvent.setup()
  renderView()

  await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())
  await user.click(screen.getByRole('button', { name: 'Expand' }))
  await waitFor(() => expect(screen.getByText('#Saga 1')).toBeInTheDocument())

  navigateToThread('2')

  await waitFor(() => expect(screen.getByText('Monstress')).toBeInTheDocument())
  expect(screen.queryByText('#Saga 1')).not.toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Expand' }))
  await waitFor(() => expect(screen.getByText('#Monstress 1')).toBeInTheDocument())

  expect(mockedIssuesApiList).toHaveBeenNthCalledWith(1, 1, { page_size: 100 })
  expect(mockedIssuesApiList).toHaveBeenNthCalledWith(2, 2, { page_size: 100 })
})

it('keys thread and issue caches per thread so stale issue responses never leak', async () => {
  const user = userEvent.setup()
  const firstIssues = deferred<IssueListResponse>()
  mockedIssuesApiList.mockImplementation((threadId: number) => (
    threadId === 1 ? firstIssues.promise : Promise.resolve(issueResult(threadId))
  ))
  renderView()

  await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())
  await user.click(screen.getByRole('button', { name: 'Expand' }))
  navigateToThread('2')
  await waitFor(() => expect(screen.getByText('Monstress')).toBeInTheDocument())
  await user.click(screen.getByRole('button', { name: 'Expand' }))
  await waitFor(() => expect(screen.getByText('#Monstress 1')).toBeInTheDocument())

  firstIssues.resolve(issueResult(1))
  await waitFor(() => expect(screen.queryByText('#Saga 1')).not.toBeInTheDocument())

  await waitFor(() => {
    const threadOne = queryClient.getQueryData<{ pages: IssueListResponse[] }>(
      queryKeys.thread.issuePages(1),
    )
    expect(threadOne?.pages[0]?.issues[0]?.issue_number).toBe('Saga 1')
  })
  const threadTwo = queryClient.getQueryData<{ pages: IssueListResponse[] }>(
    queryKeys.thread.issuePages(2),
  )
  expect(threadTwo?.pages[0]?.issues[0]?.issue_number).toBe('Monstress 1')
})

it('keys thread detail caches per thread so stale thread failures never leak', async () => {
  const firstRequest = deferred<Thread>()
  mockedThreadsApiGet.mockImplementation((id: number) => (
    id === 1 ? firstRequest.promise : Promise.resolve(threadResult(id))
  ))
  renderView()

  navigateToThread('2')
  await waitFor(() => expect(screen.getByText('Monstress')).toBeInTheDocument())

  const rejectedRequest = deferred<Thread>()
  mockedThreadsApiGet.mockImplementation((id: number) => (
    id === 1 ? rejectedRequest.promise : Promise.resolve(threadResult(id))
  ))
  navigateToThread('1')
  navigateToThread('2')
  await waitFor(() => expect(screen.getByText('Monstress')).toBeInTheDocument())
  firstRequest.resolve(threadResult(1))
  rejectedRequest.reject(new Error('stale failure'))
  // Suppress unhandled rejection from stale query that was unmounted
  rejectedRequest.promise.catch(() => {})
  await waitFor(() => expect(screen.queryByText('stale failure')).not.toBeInTheDocument())

  const saga = queryClient.getQueryData<Thread>(queryKeys.thread.detail(1))
  expect(saga?.title).toBe('Saga')
  const monstress = queryClient.getQueryData<Thread>(queryKeys.thread.detail(2))
  expect(monstress?.title).toBe('Monstress')
})

it('handles a route without a thread id without making requests', async () => {
  renderView('')

  await waitFor(() => expect(screen.getByText('Thread not found')).toBeInTheDocument())
  expect(mockedThreadsApiGet).not.toHaveBeenCalled()
  expect(mockedIssuesApiList).not.toHaveBeenCalled()
})

it('handles a non-numeric thread id without making requests', async () => {
  renderView('abc')

  await waitFor(() => expect(screen.getByText('Thread not found')).toBeInTheDocument())
  expect(mockedThreadsApiGet).not.toHaveBeenCalled()
  expect(mockedIssuesApiList).not.toHaveBeenCalled()
})
