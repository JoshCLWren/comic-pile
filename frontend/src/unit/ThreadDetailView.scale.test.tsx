import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import ThreadDetailView from '../pages/ThreadDetailView'
import { useUpdateThread } from '../hooks/useThread'
import { threadsApi } from '../services/api'
import { issuesApi } from '../services/api-issues'

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return {
    ...actual,
    useNavigate: () => vi.fn(),
    useParams: () => ({ id: '1' }),
  }
})

vi.mock('../hooks/useThread', () => ({ useUpdateThread: vi.fn() }))
vi.mock('../services/api', () => ({
  threadsApi: { get: vi.fn() },
  dependenciesApi: {
    getIssueDependencies: vi.fn().mockResolvedValue({ incoming: [], outgoing: [] }),
  },
}))
vi.mock('../services/api-issues', () => ({
  issuesApi: { list: vi.fn() },
}))

const mockedUseUpdateThread = vi.mocked(useUpdateThread)
const mockedThreadsApiGet = vi.mocked(threadsApi.get)
const mockedIssuesApiList = vi.mocked(issuesApi.list)

beforeEach(() => {
  vi.clearAllMocks()
  mockedUseUpdateThread.mockReturnValue({ mutate: vi.fn(), isPending: false } as never)
})

it.each([25, 250, 1_000, 10_000])(
  'renders metadata for a %,d-issue thread without requesting issue rows',
  async (totalIssues) => {
    mockedThreadsApiGet.mockResolvedValue({
      id: 1,
      title: `Scale Test ${totalIssues}`,
      format: 'Comics',
      issues_remaining: totalIssues - 1,
      queue_position: 1,
      status: 'active',
      total_issues: totalIssues,
      next_unread_issue_number: '2',
      notes: null,
    } as never)

    render(<ThreadDetailView />)

    await waitFor(() => {
      expect(screen.getByText(`Scale Test ${totalIssues}`)).toBeInTheDocument()
    })

    expect(screen.getByText(`Issues (${totalIssues})`)).toBeInTheDocument()
    expect(screen.getByText('Next up: #2')).toBeInTheDocument()
    expect(mockedIssuesApiList).not.toHaveBeenCalled()
  },
)

it('keeps unmigrated threads independent from the issue-list endpoint', async () => {
  mockedThreadsApiGet.mockResolvedValue({
    id: 1,
    title: 'Legacy Thread',
    format: 'Comics',
    issues_remaining: 12,
    queue_position: 3,
    status: 'active',
    total_issues: null,
    notes: null,
  } as never)

  render(<ThreadDetailView />)

  await waitFor(() => {
    expect(screen.getByText('Legacy Thread')).toBeInTheDocument()
  })

  expect(screen.getByText('12 issues')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Expand' })).not.toBeInTheDocument()
  expect(mockedIssuesApiList).not.toHaveBeenCalled()
})
