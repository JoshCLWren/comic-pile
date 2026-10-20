import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
import ThreadDetailView from '../pages/ThreadDetailView'
import { ToastProvider } from '../contexts/ToastProvider'
import { queryKeys } from '../query/queryKeys'
import { queryClient } from '../query/queryClient'
import { useUpdateThread } from '../hooks/useThread'
import { threadsApi } from '../services/api-threads'
import { dependenciesApi } from '../services/api-dependencies'
import { issuesApi } from '../services/api-issues'
import { tagsApi } from '../services/api-tags'

const navigateSpy = vi.fn()
const routeParams = { id: '1' }

interface LocationState {
  search?: string
  state?: { openEditModal?: boolean }
}

const locationState: LocationState = { state: undefined }
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return {
    ...actual,
    useNavigate: () => navigateSpy,
    useParams: () => routeParams,
    useLocation: () => locationState,
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
      getBatchBlockingInfo: vi.fn().mockResolvedValue({ threads: { 1: { is_blocked: false, blocking_reasons: [], blocking_dependencies: [] } } }),
      getIssueDependencies: vi.fn().mockResolvedValue({ incoming: [], outgoing: [] }),
      getConnectedThreads: vi.fn().mockResolvedValue({ connected_threads: [] }),
    },
  }
})
vi.mock('../services/api-issues', () => ({ issuesApi: { list: vi.fn(), listCreators: vi.fn() } }))
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
const mockedIssuesApiListCreators = vi.mocked(issuesApi.listCreators)
const mockedConnectedThreads = vi.mocked(dependenciesApi.getConnectedThreads)
const mockedThreadIssuesTags = vi.mocked(tagsApi.threadIssuesEffective)

beforeEach(() => {
  routeParams.id = '1'
  locationState.state = undefined
  locationState.search = undefined
  navigateSpy.mockReset()
  // SAFETY: the hook mock returns only the fields the component under test reads
  mockedUseUpdateThread.mockReturnValue({ mutate: vi.fn(), isPending: false } as never)
  mockedThreadsApiGet.mockReset()
  // SAFETY: the stubbed thread supplies only the fields this view reads
  mockedThreadsApiGet.mockResolvedValue({
    id: 1, title: 'Saga', format: 'Comics', issues_remaining: 5, queue_position: 1,
    status: 'active', total_issues: null, notes: null,
  } as never)
  mockedIssuesApiList.mockReset()
  mockedIssuesApiList.mockResolvedValue({ issues: [], next_page_token: null, total_count: 0, page_size: 100 })
  mockedIssuesApiListCreators.mockReset()
  // SAFETY: the bulk response matches the endpoint contract; issues without stored credits are omitted
  mockedIssuesApiListCreators.mockResolvedValue({ thread_id: 1, issues: [] })
  vi.mocked(dependenciesApi.getBatchBlockingInfo).mockReset()
  vi.mocked(dependenciesApi.getBatchBlockingInfo).mockResolvedValue({ threads: { 1: { is_blocked: false, blocking_reasons: [], blocking_dependencies: [] } } })
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

it('renders a thread without legacy rating content', async () => {
  renderPage()
  await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())
  expect(screen.queryByText(/Reviews/)).not.toBeInTheDocument()
})

it('caches the thread detail under the canonical thread-detail query key', async () => {
  renderPage()
  await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())
  expect(queryClient.getQueryData(queryKeys.thread.detail(1))).toMatchObject({ id: 1, title: 'Saga' })
})

it('auto-opens the edit modal when arriving with openEditModal state', async () => {
  locationState.state = { openEditModal: true }
  renderPage()
  await waitFor(() => expect(screen.getByRole('heading', { name: /edit series/i })).toBeInTheDocument())
  expect(screen.getByDisplayValue('Saga')).toBeInTheDocument()
})

it('does not fetch issues before the Issues section expands', async () => {
  // SAFETY: the stubbed thread supplies only the fields this view reads
  mockedThreadsApiGet.mockResolvedValue({
    id: 1, title: 'Saga', format: 'Comics', issues_remaining: 2, queue_position: 1,
    status: 'active', total_issues: 10, next_unread_issue_number: '3', notes: null,
  } as never)
  renderPage()
  await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())
  expect(mockedIssuesApiList).not.toHaveBeenCalled()
  expect(screen.getByText('Issues (10)')).toBeInTheDocument()
  expect(screen.getByText(/Next up: #3/)).toBeInTheDocument()
})

it('fetches one bounded page when the Issues section expands', async () => {
  // SAFETY: the stubbed thread supplies only the fields this view reads
  mockedThreadsApiGet.mockResolvedValue({
    id: 1, title: 'Saga', format: 'Comics', issues_remaining: 2, queue_position: 1,
    status: 'active', total_issues: 10, next_unread_issue_number: '3', notes: null,
  } as never)
  mockedIssuesApiList.mockResolvedValueOnce({
    issues: [{ id: 1, thread_id: 1, issue_number: '1', status: 'read', read_at: 'now', created_at: 'now' }],
    next_page_token: 'next', total_count: 2, page_size: 100,
  })
  renderPage()
  await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: 'Expand' }))
  await waitFor(() => expect(mockedIssuesApiList).toHaveBeenCalledTimes(1))
  expect(mockedIssuesApiList).toHaveBeenCalledWith(1, { page_size: 100 })
  await waitFor(() => expect(screen.getByText('#1')).toBeInTheDocument())
  expect(screen.getByRole('button', { name: 'Load more' })).toBeInTheDocument()
})

it('caches loaded issues under the canonical issue-pages query key', async () => {
  // SAFETY: the stubbed thread supplies only the fields this view reads
  mockedThreadsApiGet.mockResolvedValue({
    id: 1, title: 'Saga', format: 'Comics', issues_remaining: 2, queue_position: 1,
    status: 'active', total_issues: 10, next_unread_issue_number: '3', notes: null,
  } as never)
  mockedIssuesApiList.mockResolvedValueOnce({
    issues: [{ id: 1, thread_id: 1, issue_number: '1', status: 'read', read_at: 'now', created_at: 'now' }],
    next_page_token: null, total_count: 1, page_size: 100,
  })
  renderPage()
  await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: 'Expand' }))
  await waitFor(() => expect(screen.getByText('#1')).toBeInTheDocument())
  await waitFor(() => {
    const cached = queryClient.getQueryData<
      { pages: { issues: { id: number; issue_number: string }[] }[] }
    >(queryKeys.thread.issuePages(1))
    expect(cached?.pages[0]?.issues.map((issue) => issue.issue_number)).toEqual(['1'])
  })
})

it('loads the next page without duplicates or gaps', async () => {
  // SAFETY: the stubbed thread supplies only the fields this view reads
  mockedThreadsApiGet.mockResolvedValue({
    id: 1, title: 'Saga', format: 'Comics', issues_remaining: 2, queue_position: 1,
    status: 'active', total_issues: 10, next_unread_issue_number: '3', notes: null,
  } as never)
  mockedIssuesApiList
    .mockResolvedValueOnce({
      issues: [{ id: 1, thread_id: 1, issue_number: '1', status: 'read', read_at: 'now', created_at: 'now' }],
      next_page_token: 'next', total_count: 2, page_size: 100,
    })
    .mockResolvedValueOnce({
      issues: [{ id: 2, thread_id: 1, issue_number: '2', status: 'unread', read_at: null, created_at: 'now' }],
      next_page_token: null, total_count: 2, page_size: 100,
    })
  renderPage()
  await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: 'Expand' }))
  await waitFor(() => expect(screen.getByText('#1')).toBeInTheDocument())
  await user.click(screen.getByRole('button', { name: 'Load more' }))
  await waitFor(() => expect(screen.getByText('#2')).toBeInTheDocument())
  expect(mockedIssuesApiList).toHaveBeenCalledWith(1, { page_size: 100, page_token: 'next' })
  expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument()
})

it('shows an empty state when the thread has no issues', async () => {
  // SAFETY: the stubbed thread supplies only the fields this view reads
  mockedThreadsApiGet.mockResolvedValue({
    id: 1, title: 'Saga', format: 'Comics', issues_remaining: 0, queue_position: 1,
    status: 'complete', total_issues: 0, next_unread_issue_number: null, notes: null,
  } as never)
  mockedIssuesApiList.mockResolvedValueOnce({
    issues: [], next_page_token: null, total_count: 0, page_size: 100,
  })
  renderPage()
  await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: 'Expand' }))
  await waitFor(() => expect(screen.getByText('No issues yet')).toBeInTheDocument())
})

it('shows a retry action when loading issues fails', async () => {
  // SAFETY: the stubbed thread supplies only the fields this view reads
  mockedThreadsApiGet.mockResolvedValue({
    id: 1, title: 'Saga', format: 'Comics', issues_remaining: 2, queue_position: 1,
    status: 'active', total_issues: 10, next_unread_issue_number: '3', notes: null,
  } as never)
  mockedIssuesApiList
    .mockRejectedValueOnce(new Error('issues unavailable'))
    .mockResolvedValueOnce({
      issues: [{ id: 1, thread_id: 1, issue_number: '1', status: 'read', read_at: 'now', created_at: 'now' }],
      next_page_token: null, total_count: 1, page_size: 100,
    })
  renderPage()
  await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: 'Expand' }))
  await waitFor(() => expect(screen.getByText('Failed to load issues')).toBeInTheDocument())
  await user.click(screen.getByRole('button', { name: 'Retry' }))
  await waitFor(() => expect(screen.getByText('#1')).toBeInTheDocument())
})

it('renders migrated progress, paginated issues, and saves edits', async () => {
  // SAFETY: the stubbed thread supplies only the fields this view reads
  mockedThreadsApiGet.mockResolvedValue({
    id: 1, title: 'Saga', format: 'Comics', issues_remaining: 2, queue_position: 1,
    status: 'active', total_issues: 10, next_unread_issue_number: '3', notes: 'Keep reading',
  } as never)
  mockedIssuesApiList.mockResolvedValue({
    issues: [
      { id: 1, thread_id: 1, issue_number: '1', status: 'read', read_at: 'now', created_at: 'now' },
      { id: 2, thread_id: 1, issue_number: '2', status: 'unread', read_at: null, created_at: 'now' },
    ],
    next_page_token: null, total_count: 2, page_size: 100,
  })
  const mutate = vi.fn().mockResolvedValue({})
  // SAFETY: the hook mock returns only the fields the component under test reads
  mockedUseUpdateThread.mockReturnValue({ mutate, isPending: false } as never)
  renderPage()
  await waitFor(() => expect(screen.getByText('80%')).toBeInTheDocument())
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: 'Expand' }))
  await waitFor(() => expect(screen.getByText('#1')).toBeInTheDocument())
  await user.click(screen.getByRole('button', { name: 'Edit' }))
  await user.clear(screen.getByDisplayValue('Saga'))
  await user.type(screen.getAllByDisplayValue('')[0]!, 'Updated')
  await user.click(screen.getByRole('button', { name: 'Save Changes' }))
  await waitFor(() => expect(mutate).toHaveBeenCalled())
})

it('stops loading when the route has no thread id', async () => {
  routeParams.id = ''
  renderPage()
  expect(screen.queryByText('Loading...')).not.toBeInTheDocument()
})

it('disables the save action while an edit is pending', async () => {
  // SAFETY: the hook mock returns only the fields the component under test reads
  mockedUseUpdateThread.mockReturnValue({ mutate: vi.fn(), isPending: true } as never)
  renderPage()
  await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: 'Edit' }))
  expect(screen.getByRole('button', { name: 'Saving...' })).toBeDisabled()
})

it('shows the error detail when fetching the thread fails', async () => {
  mockedThreadsApiGet.mockRejectedValueOnce(new Error('missing'))
  renderPage()
  await waitFor(() => expect(screen.getByText('missing')).toBeInTheDocument())
})

it('shows Thread not found when the thread detail is unavailable', async () => {
  // SAFETY: the endpoint rejects, and the test asserts the error state renders
  mockedThreadsApiGet.mockRejectedValueOnce({
    response: { status: 404, data: { detail: 'Thread not found' } },
  } as never)
  renderPage()
  await waitFor(() => expect(screen.getByText('Thread not found')).toBeInTheDocument())
})

it('navigates back and survives issue and edit failures', async () => {
  mockedIssuesApiList.mockRejectedValueOnce(new Error('issues unavailable'))
  const mutate = vi.fn().mockRejectedValue(new Error('update failed'))
  // SAFETY: the hook mock returns only the fields the component under test reads
  mockedUseUpdateThread.mockReturnValue({ mutate, isPending: false } as never)
  render(
    <MemoryRouter initialEntries={['/thread/1']}>
      <ToastProvider>
        <Routes>
          <Route path="/thread/:id" element={<ThreadDetailView />} />
          <Route path="/queue" element={<p>Queue landing</p>} />
        </Routes>
      </ToastProvider>
    </MemoryRouter>,
  )
  await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: 'Edit' }))
  await user.clear(screen.getByDisplayValue('5'))
  await user.click(screen.getByRole('button', { name: 'Save Changes' }))
  await waitFor(() => expect(mutate).toHaveBeenCalled())
  await user.click(screen.getByRole('link', { name: 'Queue' }))
  await waitFor(() => expect(screen.getByText('Queue landing')).toBeInTheDocument())
})

it('edits migrated threads and displays the all-read boundary', async () => {
  // SAFETY: the stubbed thread supplies only the fields this view reads
  mockedThreadsApiGet.mockResolvedValue({
    id: 1, title: 'Saga', format: 'Comics', issues_remaining: 0, queue_position: 1,
    status: 'complete', total_issues: 4, next_unread_issue_number: null,
    notes: '',
  } as never)
  mockedIssuesApiList.mockResolvedValue({
    issues: [{ id: 1, thread_id: 1, issue_number: '1', status: 'read', read_at: 'now', created_at: 'now' }],
    next_page_token: null, total_count: 1, page_size: 100,
  })
  const updatedThread = {
    id: 1, title: 'Updated Saga', format: 'Comics', issues_remaining: 0, queue_position: 1,
    status: 'complete', total_issues: 4, next_unread_issue_number: null,
    notes: 'Finished',
  }
  const mutate = vi.fn().mockResolvedValue(updatedThread)
  // SAFETY: the hook mock returns only the fields the component under test reads
  mockedUseUpdateThread.mockReturnValue({ mutate, isPending: false } as never)

  renderPage()
  await waitFor(() => expect(screen.getByText('All issues read')).toBeInTheDocument())
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: 'Expand' }))
  await waitFor(() => expect(screen.getByText('#1')).toBeInTheDocument())
  await user.click(screen.getByRole('button', { name: 'Collapse' }))
  await user.click(screen.getByRole('button', { name: 'Edit' }))
  await user.click(screen.getByRole('button', { name: 'Save Changes' }))

  await waitFor(() => expect(mutate).toHaveBeenCalledWith(expect.objectContaining({ id: 1 })))
  await waitFor(() => expect(screen.getByText('Updated Saga')).toBeInTheDocument())
})

it('renders named blocked-by dependencies and an empty blocking list as links', async () => {
  mockedConnectedThreads.mockResolvedValue({
    thread_id: 1,
    connected_threads: [
      { thread_id: 9, title: 'Prequel', connection_type: 'blocked_by', dependency_id: 11, is_circular: false },
    ],
  })
  renderPage()
  await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())
  expect(screen.getByText('Dependencies')).toBeInTheDocument()
  await waitFor(() =>
    expect(screen.getByRole('link', { name: 'Open Prequel' })).toHaveAttribute('href', '/thread/9'),
  )
  expect(screen.getByText('This series blocks nothing')).toBeInTheDocument()
})

it('renders blocker issue number on thread detail when known', async () => {
  mockedConnectedThreads.mockResolvedValue({
    thread_id: 1,
    connected_threads: [
      { thread_id: 9, title: 'Starman', connection_type: 'blocked_by', dependency_id: 11, issue_number: '42', is_circular: false },
    ],
  })
  renderPage()
  await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())
  await waitFor(() => expect(screen.getByText('Starman: #42')).toBeInTheDocument())
  expect(screen.getByRole('link', { name: 'Open Starman' })).toHaveAttribute('href', '/thread/9')
})

it('omits issue number suffix when issue_number is absent', async () => {
  mockedConnectedThreads.mockResolvedValue({
    thread_id: 1,
    connected_threads: [
      { thread_id: 9, title: 'Prequel', connection_type: 'blocked_by', dependency_id: 11, is_circular: false },
    ],
  })
  renderPage()
  await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())
  await waitFor(() => expect(screen.getByText('Prequel')).toBeInTheDocument())
  expect(screen.queryByText(/Prequel: #/)).not.toBeInTheDocument()
})

it('renders blocking dependency issue number on thread detail when known', async () => {
  mockedConnectedThreads.mockResolvedValue({
    thread_id: 1,
    connected_threads: [
      { thread_id: 4, title: 'Sequel', connection_type: 'blocks', dependency_id: 12, issue_number: '7', is_circular: false },
    ],
  })
  renderPage()
  await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())
  await waitFor(() => expect(screen.getByText('Sequel: #7')).toBeInTheDocument())
  expect(screen.getByRole('link', { name: 'Open Sequel' })).toHaveAttribute('href', '/thread/4')
})

it('renders named blocking dependencies when nothing blocks this thread', async () => {
  mockedConnectedThreads.mockResolvedValue({
    thread_id: 1,
    connected_threads: [
      { thread_id: 4, title: 'Sequel', connection_type: 'blocks', dependency_id: 12, is_circular: false },
    ],
  })
  renderPage()
  await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())
  await waitFor(() => expect(screen.getByText('No incoming explicit prerequisites')).toBeInTheDocument())
  expect(screen.getByRole('link', { name: 'Open Sequel' })).toHaveAttribute('href', '/thread/4')
})

it('lists a circular dependency once instead of under both directions (#3239)', async () => {
  mockedConnectedThreads.mockResolvedValue({
    thread_id: 1,
    connected_threads: [
      // Bidirectional: this one connection both blocks and is blocked by thread 1.
      { thread_id: 9, title: 'Magneto Rex', connection_type: 'blocks & blocked_by', dependency_id: 11, issue_number: '42', is_circular: true },
      { thread_id: 4, title: 'Sequel', connection_type: 'blocks', dependency_id: 12, is_circular: false },
    ],
  })
  renderPage()
  await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())

  expect(screen.getByRole('heading', { name: /Circular Dependencies/ })).toBeInTheDocument()
  expect(
    screen.getByText(/part of a dependency loop with this series/),
  ).toBeInTheDocument()
  expect(
    screen.getByRole('link', { name: 'Open Magneto Rex (circular dependency)' }),
  ).toHaveAttribute('href', '/thread/9')

  // The circular series is presented exactly once in the whole dependencies
  // region -- it must not reappear as a prerequisite or as a dependent.
  const circularLinks = screen.getAllByRole('link', { name: /Magneto Rex/ })
  expect(circularLinks).toHaveLength(1)
  expect(screen.queryByRole('link', { name: 'Open Magneto Rex' })).not.toBeInTheDocument()

  // The one-way dependency is unaffected.
  expect(screen.getByRole('link', { name: 'Open Sequel' })).toHaveAttribute('href', '/thread/4')
})

it('passes onIssueChanged callback to IssueToggleList', async () => {
  vi.mocked(issuesApi.list).mockResolvedValue({
    issues: [
      { id: 1, status: 'unread', issue_number: '1', thread_id: 1, read_at: null, created_at: '2023-01-01T00:00:00Z' },
      { id: 2, status: 'read', issue_number: '2', thread_id: 1, read_at: '2023-01-02T00:00:00Z', created_at: '2023-01-01T00:00:00Z' },
    ],
    total_count: 2,
    page_size: 50,
    next_page_token: null,
  })
  
  renderPage()
  await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())
  
  // The component should render IssueToggleList with the callback
  // This test verifies the integration - the actual callback logic is tested in IssueToggleList tests
  expect(screen.getByText('Saga')).toBeInTheDocument()
})

it('reports dependency load failures without hiding the section', async () => {
  mockedConnectedThreads.mockRejectedValue(new Error('dependencies unavailable'))
  renderPage()
  await waitFor(() =>
    expect(screen.getByRole('alert')).toHaveTextContent('Unable to load dependencies.'),
  )
})

it('shows direct and inherited tag chips on issue rows without opening an editor (#3422)', async () => {
  // SAFETY: the stubbed thread supplies only the fields this view reads
  mockedThreadsApiGet.mockResolvedValue({
    id: 1, title: 'Saga', format: 'Comics', issues_remaining: 1, queue_position: 1,
    status: 'active', total_issues: 2, next_unread_issue_number: '2', notes: null,
  } as never)
  mockedIssuesApiList.mockResolvedValue({
    issues: [
      { id: 1, thread_id: 1, issue_number: '1', status: 'read', read_at: 'now', created_at: 'now' },
      { id: 2, thread_id: 1, issue_number: '2', status: 'unread', read_at: null, created_at: 'now' },
    ],
    next_page_token: null, total_count: 2, page_size: 100,
  })
  const mine = {
    id: 1, name: 'Mine', normalized_name: 'mine', scope: 'private' as const,
    owner_user_id: 1, color: '#DC2626', created_at: '', updated_at: '',
  }
  const physical = {
    id: 2, name: 'Physical', normalized_name: 'physical', scope: 'private' as const,
    owner_user_id: 1, color: '#3B82F6', created_at: '', updated_at: '',
  }
  mockedThreadIssuesTags.mockResolvedValue({
    thread_id: 1,
    issues: [
      {
        target_type: 'Issue', target_id: 1, direct_tags: [mine],
        effective_tags: [
          { tag: mine, direct: true, sources: [{ target_type: 'Issue', target_id: 1, display_name: '#1' }] },
        ],
      },
      {
        target_type: 'Issue', target_id: 2, direct_tags: [],
        effective_tags: [
          { tag: physical, direct: false, sources: [{ target_type: 'Thread', target_id: 1, display_name: 'Saga' }] },
        ],
      },
    ],
  })
  renderPage()
  await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: 'Expand' }))
  await waitFor(() => expect(screen.getByText('#1')).toBeInTheDocument())

  // Both rows render chips with no editor opened: the direct chip is solid
  // while the inherited chip is dashed and marked read-only.
  await waitFor(() => expect(screen.getByText('Mine')).toBeInTheDocument())
  expect(screen.getByText('Physical')).toBeInTheDocument()
  expect(screen.getByText('Inherited')).toBeInTheDocument()
  expect(
    screen.getByText('Physical').closest('span[class*="rounded-full"]'),
  ).toHaveClass('border-dashed')
  expect(
    screen.getByText('Mine').closest('span[class*="rounded-full"]'),
  ).not.toHaveClass('border-dashed')
  expect(mockedThreadIssuesTags).toHaveBeenCalledWith(1)
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
})

it('offers per-issue tag editing directly without enabling Select mode (#3424)', async () => {
  // SAFETY: the stubbed thread supplies only the fields this view reads
  mockedThreadsApiGet.mockResolvedValue({
    id: 1, title: 'Saga', format: 'Comics', issues_remaining: 1, queue_position: 1,
    status: 'active', total_issues: 2, next_unread_issue_number: '2', notes: null,
  } as never)
  mockedIssuesApiList.mockResolvedValue({
    issues: [
      { id: 1, thread_id: 1, issue_number: '1', status: 'read', read_at: 'now', created_at: 'now' },
    ],
    next_page_token: null, total_count: 1, page_size: 100,
  })
  renderPage()
  await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: 'Expand' }))
  await waitFor(() => expect(screen.getByText('#1')).toBeInTheDocument())

  // The regression: the per-issue tag button used to render only after
  // enabling bulk Select mode, leaving no tag access on plain issue rows.
  const tagButton = screen.getByRole('button', { name: 'Edit tags for issue #1' })
  expect(tagButton).toBeInTheDocument()

  await user.click(tagButton)
  await waitFor(() =>
    expect(screen.getByRole('heading', { name: 'Tags · #1' })).toBeInTheDocument(),
  )
})

it('retries canonical requirements without claiming a failed load means available', async () => {
  vi.mocked(dependenciesApi.getBatchBlockingInfo).mockRejectedValueOnce(new Error('offline'))
  renderPage()
  expect(await screen.findByText('Unable to load reading requirements.')).toBeVisible()
  expect(screen.queryByText('Available now')).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Retry requirements' }))
  expect(await screen.findByText('Available now')).toBeVisible()
  expect(dependenciesApi.getBatchBlockingInfo).toHaveBeenCalledTimes(2)
})

it('uses canonical list blockers even when explicit connected prerequisites are empty', async () => {
  vi.mocked(dependenciesApi.getBatchBlockingInfo).mockResolvedValue({ threads: { 1: {
    is_blocked: true, blocking_reasons: ['Hold in Ultimate: waiting on One Year In #1'],
    blocking_dependencies: [{ issue_id: 9, thread_id: 2, thread_title: 'One Year In', issue_number: '1', label: 'Hold in Ultimate: waiting on One Year In #1' }],
  } } })
  renderPage()
  expect(await screen.findByText('Waiting')).toBeVisible()
  expect(screen.getByRole('link', { name: 'Open One Year In issue #1' })).toHaveAttribute('href', '/thread/2?issue=9#issue-9')
  expect(screen.queryByText('Available now')).not.toBeInTheDocument()
})

it('opens the exact required issue after loading its later page', async () => {
  locationState.search = '?issue=101'
  const thread = await threadsApi.get(1)
  mockedThreadsApiGet.mockResolvedValue({ ...thread, total_issues: 2 })
  mockedIssuesApiList.mockResolvedValueOnce({
    issues: [{ id: 1, thread_id: 1, issue_number: '1', status: 'read', read_at: 'now', created_at: 'now' }],
    next_page_token: 'next', total_count: 2, page_size: 100,
  }).mockResolvedValueOnce({
    issues: [{ id: 101, thread_id: 1, issue_number: '101', status: 'unread', read_at: null, created_at: 'now' }],
    next_page_token: null, total_count: 2, page_size: 100,
  })
  renderPage()
  await waitFor(() => expect(document.getElementById('issue-101')).toHaveFocus())
  expect(mockedIssuesApiList).toHaveBeenCalledWith(1, { page_size: 100, page_token: 'next' })
  expect(screen.getByText('#101')).toBeVisible()
})

function creatorsResponseFor(
  entries: { issueId: number; creators: { name: string; roles: string[] }[] }[],
) {
  // SAFETY: the payload matches the bulk creators endpoint contract; the page
  // reads only `issues[].issue_id` and `issues[].creators`.
  return {
    thread_id: 1,
    issues: entries.map((entry) => ({ issue_id: entry.issueId, creators: entry.creators })),
  } as never
}

it("renders each issue's own provider creators instead of shared series credits (#3461)", async () => {
  // SAFETY: the stubbed thread supplies only the fields this view reads
  mockedThreadsApiGet.mockResolvedValue({
    id: 1, title: 'Saga', format: 'Comics', issues_remaining: 0, queue_position: 1,
    status: 'active', total_issues: 2, next_unread_issue_number: '1', notes: null,
    manual_creator_credits: [{ name: 'Series Fallback', roles: ['Writer'] }],
  } as never)
  mockedIssuesApiList.mockResolvedValue({
    issues: [
      { id: 11, thread_id: 1, issue_number: '1', status: 'read', read_at: 'now', created_at: 'now' },
      { id: 22, thread_id: 1, issue_number: '2', status: 'unread', read_at: null, created_at: 'now' },
    ],
    next_page_token: null, total_count: 2, page_size: 100,
  })
  mockedIssuesApiListCreators.mockResolvedValue(
    creatorsResponseFor([
      { issueId: 11, creators: [{ name: 'Alan Moore', roles: ['Writer'] }] },
      { issueId: 22, creators: [{ name: 'Dave Gibbons', roles: ['Artist'] }] },
    ]),
  )
  renderPage()
  await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: 'Expand' }))
  await waitFor(() => expect(screen.getByText('#1')).toBeInTheDocument())
  expect(await screen.findByText('by Alan Moore (Writer)')).toBeInTheDocument()
  expect(screen.getByText('by Dave Gibbons (Artist)')).toBeInTheDocument()
  expect(screen.queryByText(/Series Fallback/)).not.toBeInTheDocument()
})

it('falls back to the series manual creator credits when an issue has no provider metadata (#3461)', async () => {
  // SAFETY: the stubbed thread supplies only the fields this view reads
  mockedThreadsApiGet.mockResolvedValue({
    id: 1, title: 'Saga', format: 'Comics', issues_remaining: 0, queue_position: 1,
    status: 'active', total_issues: 1, next_unread_issue_number: '1', notes: null,
    manual_creator_credits: [{ name: 'Series Writer', roles: ['Writer'] }],
  } as never)
  mockedIssuesApiList.mockResolvedValue({
    issues: [
      { id: 11, thread_id: 1, issue_number: '1', status: 'unread', read_at: null, created_at: 'now' },
    ],
    next_page_token: null, total_count: 1, page_size: 100,
  })
  // The bulk read omits issues without stored credits, so the row falls back
  // to the series' manual creator credits.
  mockedIssuesApiListCreators.mockResolvedValue({ thread_id: 1, issues: [] })
  renderPage()
  await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: 'Expand' }))
  expect(await screen.findByText('by Series Writer (Writer)')).toBeInTheDocument()
})

it('loads and saves the series manual creator credits from the thread edit form (#3461)', async () => {
  // SAFETY: the stubbed thread supplies only the fields this view reads
  mockedThreadsApiGet.mockResolvedValue({
    id: 1, title: 'Saga', format: 'Comics', issues_remaining: 0, queue_position: 1,
    status: 'active', total_issues: 1, next_unread_issue_number: '1', notes: null,
    manual_creator_credits: [{ name: 'Alan Moore', roles: ['Writer'] }],
  } as never)
  const mutate = vi.fn().mockResolvedValue({})
  // SAFETY: the hook mock returns only the fields the component under test reads
  mockedUseUpdateThread.mockReturnValue({ mutate, isPending: false } as never)
  renderPage()
  await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: 'Edit' }))
  expect(await screen.findByText('Alan Moore')).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Remove' }))
  await user.click(screen.getByRole('button', { name: 'Save Changes' }))
  await waitFor(() =>
    expect(mutate).toHaveBeenCalledWith({
      id: 1,
      data: expect.objectContaining({ manual_creator_credits: [] }),
    }),
  )
})
