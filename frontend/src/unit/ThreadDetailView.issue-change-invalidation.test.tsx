import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
import ThreadDetailView from '../pages/ThreadDetailView'
import { ToastProvider } from '../contexts/ToastProvider'
import { invalidateAfterIssueEdit } from '../query/cacheEffects'
import { queryClient } from '../query/queryClient'
import { useUpdateThread } from '../hooks/useThread'
import { threadsApi } from '../services/api-threads'
import { dependenciesApi } from '../services/api-dependencies'
import { readingBoundariesApi } from '../services/api-reading-boundaries'
import { issuesApi } from '../services/api-issues'
import { tagsApi } from '../services/api-tags'

const routeParams = { id: '1' }

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useParams: () => routeParams }
})

vi.mock('../hooks/useThread', async () => {
  const actual = await vi.importActual<typeof import('../hooks/useThread')>('../hooks/useThread')
  return { ...actual, useUpdateThread: vi.fn() }
})

vi.mock('../query/cacheEffects', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../query/cacheEffects')>()
  return { ...actual, invalidateAfterIssueEdit: vi.fn().mockResolvedValue(undefined) }
})

vi.mock('../services/api-threads', () => ({ threadsApi: { get: vi.fn(), update: vi.fn() } }))
vi.mock('../services/api-dependencies', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/api-dependencies')>()
  return {
    ...actual,
    dependenciesApi: {
      getBatchBlockingInfo: vi.fn().mockResolvedValue({ threads: { 1: { is_blocked: false, blocking_reasons: [], blocking_dependencies: [] } } }),
      getIssueDependencies: vi.fn().mockResolvedValue({ incoming: [], outgoing: [] }),
      getConnectedThreads: vi.fn().mockResolvedValue({ thread_id: 1, connected_threads: [] }),
    },
  }
})
vi.mock('../services/api-reading-boundaries', () => ({ readingBoundariesApi: { batch: vi.fn() } }))
vi.mock('../services/api-issues', () => ({ issuesApi: { list: vi.fn(), listCreators: vi.fn() } }))
vi.mock('../services/api-tags', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/api-tags')>()
  return {
    ...actual,
    tagsApi: {
      list: vi.fn().mockResolvedValue({ tags: [] }),
      effectiveForIssue: vi.fn().mockResolvedValue({ target_type: 'Issue', target_id: 0, direct_tags: [], effective_tags: [] }),
      effectiveForThread: vi.fn().mockResolvedValue({ target_type: 'Thread', target_id: 1, direct_tags: [], effective_tags: [] }),
      effectiveForPlan: vi.fn().mockResolvedValue({ target_type: 'ContinuityPlan', target_id: 0, direct_tags: [], effective_tags: [] }),
      threadIssuesEffective: vi.fn().mockResolvedValue({ thread_id: 1, issues: [] }),
    },
  }
})

vi.mock('../pages/QueuePage/IssueToggleList', async () => {
  const React = await import('react')
  return {
    IssueToggleList: React.forwardRef(function MockIssueToggleList(
      props: { onIssueChanged?: () => void },
      _ref: unknown,
    ) {
      return React.createElement(
        'button',
        { type: 'button', onClick: () => props.onIssueChanged?.() },
        'mock-issue-change',
      )
    }),
  }
})

const mockedUseUpdateThread = vi.mocked(useUpdateThread)
const mockedThreadsApiGet = vi.mocked(threadsApi.get)
const mockedIssuesApiList = vi.mocked(issuesApi.list)
const mockedIssuesApiListCreators = vi.mocked(issuesApi.listCreators)
const mockedInvalidateAfterIssueEdit = vi.mocked(invalidateAfterIssueEdit)

beforeEach(() => {
  vi.clearAllMocks()
  routeParams.id = '1'
  vi.mocked(readingBoundariesApi.batch).mockResolvedValue({
    evaluator: 'enabled',
    threads: { 1: { thread_id: 1, state: 'available', summary: 'Available now', blockers: [] } },
  })
  // SAFETY: the hook mock returns only the fields the component under test reads
  mockedUseUpdateThread.mockReturnValue({ mutate: vi.fn(), isPending: false } as never)
  // SAFETY: the stubbed thread supplies only the fields this view reads
  mockedThreadsApiGet.mockResolvedValue({
    id: 1, title: 'Saga', format: 'Comics', issues_remaining: 5, queue_position: 1,
    status: 'active', total_issues: 10, next_unread_issue_number: '1', notes: null,
  } as never)
  mockedIssuesApiList.mockResolvedValue({ issues: [], next_page_token: null, total_count: 0, page_size: 100 })
  mockedIssuesApiListCreators.mockResolvedValue({ thread_id: 1, issues: [] })
  vi.mocked(dependenciesApi.getBatchBlockingInfo).mockResolvedValue({
    threads: { 1: { is_blocked: false, blocking_reasons: [], blocking_dependencies: [] } },
  })
  vi.mocked(dependenciesApi.getConnectedThreads).mockResolvedValue({ thread_id: 1, connected_threads: [] })
  vi.mocked(tagsApi.threadIssuesEffective).mockResolvedValue({ thread_id: 1, issues: [] })
  mockedInvalidateAfterIssueEdit.mockResolvedValue(undefined)
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

it('reconciles canonical reader projections after issue mutations in the edit modal (#5537)', async () => {
  const user = userEvent.setup()
  renderPage()
  await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())

  await user.click(screen.getByRole('button', { name: 'Edit' }))
  await screen.findByLabelText('Notes')
  await user.click(screen.getByRole('button', { name: 'mock-issue-change' }))

  await waitFor(() => {
    expect(mockedInvalidateAfterIssueEdit).toHaveBeenCalledWith(queryClient, 1)
  })
})
