import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import ThreadDetailView from '../pages/ThreadDetailView'
import { useUpdateThread } from '../hooks/useThread'
import { useThreadReviews } from '../hooks/useReview'
import { threadsApi } from '../services/api'
import { issuesApi } from '../services/api-issues'

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
  render(<ThreadDetailView />)

  await waitFor(() => {
    expect(screen.getByText('Saga')).toBeInTheDocument()
  })

  expect(screen.queryByText(/Reviews/)).not.toBeInTheDocument()
  expect(screen.queryByText('No reviews yet.')).not.toBeInTheDocument()
  expect(getThreadReviewsSpy).not.toHaveBeenCalled()
})
