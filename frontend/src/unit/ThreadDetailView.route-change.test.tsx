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
vi.mock('../services/api', () => ({
  threadsApi: { get: vi.fn() },
  dependenciesApi: { getIssueDependencies: vi.fn().mockResolvedValue({ incoming: [], outgoing: [] }) },
}))
vi.mock('../services/api-issues', () => ({ issuesApi: { list: vi.fn() } }))

const mockedUseUpdateThread = vi.mocked(useUpdateThread)
const mockedThreadsApiGet = vi.mocked(threadsApi.get)
const mockedIssuesApiList = vi.mocked(issuesApi.list)

beforeEach(() => {
  routeParams.id = '1'
  mockedUseUpdateThread.mockReturnValue({ mutate: vi.fn(), isPending: false } as never)
  mockedThreadsApiGet.mockImplementation(async (id: number) => ({
    id,
    title: id === 1 ? 'Saga' : 'Monstress',
    format: 'Comics',
    issues_remaining: 1,
    queue_position: id,
    status: 'active',
    total_issues: 1,
    next_unread_issue_number: '1',
    notes: null,
  } as never))
  mockedIssuesApiList.mockImplementation(async (threadId: number) => ({
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
  }))
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
