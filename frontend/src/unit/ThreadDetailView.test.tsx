import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'
import ThreadDetailView from '../pages/ThreadDetailView'
import { useUpdateThread } from '../hooks/useThread'
import { threadsApi } from '../services/api'
import { issuesApi } from '../services/api-issues'

const navigateSpy = vi.fn()
const routeParams = { id: '1' }
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => navigateSpy, useParams: () => routeParams }
})
vi.mock('../hooks/useThread', () => ({ useUpdateThread: vi.fn() }))
vi.mock('../contexts/CollectionContext', () => ({ useCollections: () => ({ collections: [], activeCollectionId: null }) }))
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
  navigateSpy.mockReset()
  mockedUseUpdateThread.mockReturnValue({ mutate: vi.fn(), isPending: false } as never)
  mockedThreadsApiGet.mockResolvedValue({
    id: 1, title: 'Saga', format: 'Comics', issues_remaining: 5, queue_position: 1,
    status: 'active', total_issues: null, notes: null, collection_id: null,
  } as never)
  mockedIssuesApiList.mockResolvedValue({ issues: [], next_page_token: null, total_count: 0, page_size: 100 })
})

function renderPage() {
  return render(<ThreadDetailView />)
}

it('renders a thread without legacy rating content', async () => {
  renderPage()
  await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())
  expect(screen.queryByText(/Reviews/)).not.toBeInTheDocument()
})

it('renders migrated progress, paginated issues, and saves edits', async () => {
  mockedThreadsApiGet.mockResolvedValue({
    id: 1, title: 'Saga', format: 'Comics', issues_remaining: 2, queue_position: 1,
    status: 'active', total_issues: 10, next_unread_issue_number: '3', notes: 'Keep reading', collection_id: null,
  } as never)
  mockedIssuesApiList
    .mockResolvedValueOnce({ issues: [{ id: 1, thread_id: 1, issue_number: '1', status: 'read', read_at: 'now', created_at: 'now' }], next_page_token: 'next', total_count: 2, page_size: 100 })
    .mockResolvedValueOnce({ issues: [{ id: 2, thread_id: 1, issue_number: '2', status: 'unread', read_at: null, created_at: 'now' }], next_page_token: null, total_count: 2, page_size: 100 })
  const mutate = vi.fn().mockResolvedValue({})
  mockedUseUpdateThread.mockReturnValue({ mutate, isPending: false } as never)
  renderPage()
  await waitFor(() => expect(screen.getByText('80%')).toBeInTheDocument())
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: 'Expand' }))
  expect(screen.getByText('#1')).toBeInTheDocument()
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
  mockedUseUpdateThread.mockReturnValue({ mutate: vi.fn(), isPending: true } as never)
  renderPage()
  await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: 'Edit' }))
  expect(screen.getByRole('button', { name: 'Saving...' })).toBeDisabled()
})

it('handles missing threads and API errors', async () => {
  mockedThreadsApiGet.mockRejectedValueOnce(new Error('missing'))
  renderPage()
  await waitFor(() => expect(screen.getByText('missing')).toBeInTheDocument())
  mockedThreadsApiGet.mockResolvedValueOnce(null as never)
  renderPage()
  await waitFor(() => expect(screen.getByText('Thread not found')).toBeInTheDocument())
})

it('navigates back and survives issue and edit failures', async () => {
  mockedIssuesApiList.mockRejectedValueOnce(new Error('issues unavailable'))
  const mutate = vi.fn().mockRejectedValue(new Error('update failed'))
  mockedUseUpdateThread.mockReturnValue({ mutate, isPending: false } as never)
  renderPage()
  await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: 'Edit' }))
  await user.clear(screen.getByDisplayValue('5'))
  await user.click(screen.getByRole('button', { name: 'Save Changes' }))
  await waitFor(() => expect(mutate).toHaveBeenCalled())
  await user.click(screen.getByRole('button', { name: /back to queue/i }))
  expect(navigateSpy).toHaveBeenCalledWith('/queue')
})

it('edits migrated threads and displays the all-read boundary', async () => {
  mockedThreadsApiGet.mockResolvedValue({
    id: 1, title: 'Saga', format: 'Comics', issues_remaining: 0, queue_position: 1,
    status: 'complete', total_issues: 4, next_unread_issue_number: null,
    notes: '', collection_id: 7,
  } as never)
  mockedIssuesApiList.mockReset()
  mockedIssuesApiList.mockResolvedValue({
    issues: [{ id: 1, thread_id: 1, issue_number: '1', status: 'read', read_at: 'now', created_at: 'now' }],
    next_page_token: null, total_count: 1, page_size: 100,
  })
  const updatedThread = {
    id: 1, title: 'Updated Saga', format: 'Comics', issues_remaining: 0, queue_position: 1,
    status: 'complete', total_issues: 4, next_unread_issue_number: null,
    notes: 'Finished', collection_id: 7,
  }
  const mutate = vi.fn().mockResolvedValue(updatedThread)
  mockedUseUpdateThread.mockReturnValue({ mutate, isPending: false } as never)

  renderPage()
  await waitFor(() => expect(screen.getByText('All issues read')).toBeInTheDocument())
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: 'Expand' }))
  await user.click(screen.getByRole('button', { name: 'Collapse' }))
  await user.click(screen.getByRole('button', { name: 'Edit' }))
  await user.click(screen.getByRole('button', { name: 'Save Changes' }))

  await waitFor(() => expect(mutate).toHaveBeenCalledWith(expect.objectContaining({ id: 1 })))
  expect(screen.getByText('Updated Saga')).toBeInTheDocument()
})
