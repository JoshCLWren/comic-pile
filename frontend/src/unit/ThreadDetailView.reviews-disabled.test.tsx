import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import userEvent from '@testing-library/user-event'
import ThreadDetailView from '../pages/ThreadDetailView'
import { useUpdateThread } from '../hooks/useThread'
import { useThreadReviews } from '../hooks/useReview'
import { threadsApi } from '../services/api'
import { issuesApi } from '../services/api-issues'
import { CollectionProvider } from '../contexts/CollectionContext'

const navigateSpy = vi.fn()
const getThreadReviewsSpy = vi.fn()

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return {
    ...actual,
    useNavigate: () => navigateSpy,
    useParams: () => ({ id: '1' }),
  }
})

vi.mock('../config/featureFlags', () => ({
  isReviewsFeatureEnabled: vi.fn(() => false),
  collectionsEnabled: false,
}))

vi.mock('../hooks/useThread', () => ({
  useUpdateThread: vi.fn(),
}))

vi.mock('../hooks/useReview', () => ({
  useThreadReviews: vi.fn(),
}))

vi.mock('../services/api', () => ({
  threadsApi: {
    get: vi.fn(),
  },
  dependenciesApi: {
    getIssueDependencies: vi.fn().mockResolvedValue({ incoming: [], outgoing: [] }),
  },
}))

vi.mock('../services/api-issues', () => ({
  issuesApi: {
    list: vi.fn(),
  },
}))

const mockedUseUpdateThread = vi.mocked(useUpdateThread) as any
const mockedUseThreadReviews = vi.mocked(useThreadReviews) as any
const mockedThreadsApiGet = vi.mocked(threadsApi.get) as any
const mockedIssuesApiList = vi.mocked(issuesApi.list) as any

beforeEach(() => {
  navigateSpy.mockReset()
  getThreadReviewsSpy.mockReset()
  mockedUseUpdateThread.mockReturnValue({ mutate: vi.fn(), isPending: false })
  mockedUseThreadReviews.mockReturnValue({
    reviews: [],
    getThreadReviews: getThreadReviewsSpy,
    isPending: false,
    isError: false,
  })
  mockedThreadsApiGet.mockResolvedValue({
    id: 1,
    title: 'Saga',
    format: 'Comics',
    issues_remaining: 5,
    queue_position: 1,
    status: 'active',
    total_issues: null,
    notes: null,
    collection_id: null,
  })
  mockedIssuesApiList.mockResolvedValue({
    issues: [],
    next_page_token: null,
  })
})

it('hides review content and skips review loading when the feature is disabled', async () => {
  render(<CollectionProvider><ThreadDetailView /></CollectionProvider>)

  await waitFor(() => {
    expect(screen.getByText('Saga')).toBeInTheDocument()
  })

  expect(screen.queryByText(/Reviews/)).not.toBeInTheDocument()
  expect(screen.queryByText('No reviews yet.')).not.toBeInTheDocument()
  expect(getThreadReviewsSpy).not.toHaveBeenCalled()
})

it('renders migrated progress and issues, then saves an edit', async () => {
  mockedThreadsApiGet.mockResolvedValue({
    id: 1, title: 'Saga', format: 'Comics', issues_remaining: 2, queue_position: 1,
    status: 'active', total_issues: 10, next_unread_issue_number: '3', notes: 'Keep reading', collection_id: 4,
  })
  mockedIssuesApiList.mockResolvedValue({
    issues: [{ id: 1, thread_id: 1, issue_number: '1', status: 'read', read_at: 'now', created_at: 'now' }],
    next_page_token: null,
  })
  const mutate = vi.fn().mockResolvedValue({
    id: 1, title: 'Updated', format: 'Comics', issues_remaining: 2, total_issues: 10,
    queue_position: 1, status: 'active', notes: 'Changed', collection_id: null,
  })
  mockedUseUpdateThread.mockReturnValue({ mutate, isPending: false })
  render(<CollectionProvider><ThreadDetailView /></CollectionProvider>)
  await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())
  expect(screen.getByText('80%')).toBeInTheDocument()
  expect(screen.getByText('8 of 10 issues read')).toBeInTheDocument()
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: 'Edit' }))
  const titleInput = screen.getByDisplayValue('Saga')
  await user.clear(titleInput)
  await user.type(titleInput, 'Updated')
  await user.click(screen.getByRole('button', { name: 'Save Changes' }))
  await waitFor(() => expect(mutate).toHaveBeenCalled())
})

it('shows the not-found and API-error states', async () => {
  mockedThreadsApiGet.mockRejectedValueOnce(new Error('missing'))
  const { unmount } = render(<ThreadDetailView />)
  await waitFor(() => expect(screen.getByText('missing')).toBeInTheDocument())
  unmount()
  mockedThreadsApiGet.mockResolvedValueOnce(null)
  render(<CollectionProvider><ThreadDetailView /></CollectionProvider>)
  await waitFor(() => expect(screen.getByText('Thread not found')).toBeInTheDocument())
})

it('expands paginated issues, navigates back, and edits an unmigrated thread', async () => {
  mockedThreadsApiGet.mockResolvedValueOnce({
    id: 1, title: 'Saga', format: 'Comics', issues_remaining: 5, queue_position: 2,
    status: 'active', total_issues: 4, next_unread_issue_number: null, notes: 'note', collection_id: null,
  })
  mockedIssuesApiList
    .mockResolvedValueOnce({ issues: [{ id: 1, thread_id: 1, issue_number: '1', status: 'unread', read_at: null, created_at: 'now' }], next_page_token: 'next' })
    .mockResolvedValueOnce({ issues: [{ id: 2, thread_id: 1, issue_number: '2', status: 'read', read_at: 'now', created_at: 'now' }], next_page_token: null })
  const user = userEvent.setup()
  render(<CollectionProvider><ThreadDetailView /></CollectionProvider>)
  await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())
  await user.click(screen.getByRole('button', { name: 'Expand' }))
  expect(screen.getByText('#1')).toBeInTheDocument()
  expect(screen.getByText('#2')).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Collapse' }))
  await user.click(screen.getByRole('button', { name: /back to queue/i }))
  expect(navigateSpy).toHaveBeenCalledWith('/queue')
})

it('survives issue and edit failures', async () => {
  mockedThreadsApiGet.mockResolvedValueOnce({
    id: 1, title: 'Saga', format: 'Comics', issues_remaining: 5, queue_position: 1,
    status: 'active', total_issues: 3, next_unread_issue_number: '1', notes: null, collection_id: null,
  })
  mockedIssuesApiList.mockRejectedValueOnce(new Error('issues unavailable'))
  const mutate = vi.fn().mockRejectedValue(new Error('update failed'))
  mockedUseUpdateThread.mockReturnValue({ mutate, isPending: false })
  const user = userEvent.setup()
  render(<CollectionProvider><ThreadDetailView /></CollectionProvider>)
  await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())
  await user.click(screen.getByRole('button', { name: 'Edit' }))
  await user.click(screen.getByRole('button', { name: 'Save Changes' }))
  await waitFor(() => expect(mutate).toHaveBeenCalled())
})
