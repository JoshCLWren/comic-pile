import { render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import userEvent from '@testing-library/user-event'
import ThreadDetailView from '../pages/ThreadDetailView'

const api = vi.hoisted(() => ({ get: vi.fn(), list: vi.fn() }))
const update = vi.hoisted(() => vi.fn())
const reviews = vi.hoisted(() => ({ getThreadReviews: vi.fn(), reviews: [] as Array<{ id: number; rating: number; issue_number: string | null; review_text: string; created_at: string }>, isPending: false }))
vi.mock('react-router-dom', () => ({ useParams: () => ({ id: '1' }), useNavigate: () => vi.fn() }))
vi.mock('../config/featureFlags', () => ({ isReviewsFeatureEnabled: () => true, collectionsEnabled: false }))
vi.mock('../services/api', () => ({ threadsApi: { get: api.get }, dependenciesApi: { getIssueDependencies: vi.fn().mockResolvedValue({ incoming: [], outgoing: [] }) } }))
vi.mock('../services/api-issues', () => ({ issuesApi: { list: api.list } }))
vi.mock('../hooks/useThread', () => ({ useUpdateThread: () => ({ mutate: update, isPending: false }) }))
vi.mock('../hooks/useReview', () => ({ useThreadReviews: () => reviews }))
vi.mock('../contexts/CollectionContext', () => ({ CollectionProvider: ({ children }: { children: React.ReactNode }) => children, useCollections: () => ({}) }))

describe('ThreadDetailView with reviews enabled', () => {
  it('loads and renders reviews with and without issue labels', async () => {
    api.get.mockResolvedValue({ id: 1, title: 'Saga', format: 'Comic', issues_remaining: 1, total_issues: 2, queue_position: 1, status: 'active', next_unread_issue_number: '2', notes: null, collection_id: null })
    api.list.mockResolvedValue({ issues: [], next_page_token: null })
    reviews.reviews = [
      { id: 1, rating: 4.5, issue_number: '2', review_text: 'Great', created_at: '2026-01-01' },
      { id: 2, rating: 3, issue_number: null, review_text: '', created_at: '2026-01-02' },
    ]
    render(<ThreadDetailView />)
    await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())
    expect(screen.getByText('Reviews (2)')).toBeInTheDocument()
    expect(screen.getByText('Great')).toBeInTheDocument()
    expect(reviews.getThreadReviews).toHaveBeenCalledWith(1)
  })

  it('keeps the detail page usable when review loading fails', async () => {
    reviews.reviews = []
    reviews.getThreadReviews.mockRejectedValueOnce(new Error('review failed'))
    api.get.mockResolvedValueOnce({ id: 1, title: 'Saga', format: 'Comic', issues_remaining: 1, total_issues: null, queue_position: 1, status: 'active', notes: null, collection_id: null })
    const user = userEvent.setup()
    render(<ThreadDetailView />)
    await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())
    expect(screen.getByText('No reviews yet.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Edit' }))
    await user.click(screen.getByRole('button', { name: 'Save Changes' }))
  })

  it('shows the reviews loading state and pending save label', async () => {
    reviews.reviews = []
    reviews.isPending = true
    api.get.mockResolvedValue({ id: 1, title: 'Loading reviews', format: 'Comic', issues_remaining: 1, total_issues: null, queue_position: 1, status: 'active', notes: null, collection_id: null })
    render(<ThreadDetailView />)
    await waitFor(() => expect(screen.getByText('Loading reviews')).toBeInTheDocument())
    expect(screen.getByText('Loading reviews...')).toBeInTheDocument()
    reviews.isPending = false
  })

  it('expands migrated issue details and submits the edit form', async () => {
    reviews.reviews = []
    reviews.getThreadReviews.mockResolvedValue(undefined)
    api.get.mockResolvedValue({ id: 1, title: 'Saga', format: 'Comic', issues_remaining: 1, total_issues: 2, queue_position: 1, status: 'active', next_unread_issue_number: '2', notes: 'Notes', collection_id: null })
    api.list.mockResolvedValue({ issues: [
      { id: 1, issue_number: '1', status: 'read' },
      { id: 2, issue_number: '2', status: 'unread' },
    ], next_page_token: null })
    update.mockResolvedValue({ id: 1, title: 'Updated', format: 'Comic', issues_remaining: 1, total_issues: 2, queue_position: 1, status: 'active', notes: 'Notes', collection_id: null })
    const user = userEvent.setup()
    render(<ThreadDetailView />)
    await waitFor(() => expect(screen.getByText('Issues (2)')).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'Expand' }))
    expect(screen.getByText('#1')).toBeInTheDocument()
    expect(screen.getByText('Read')).toBeInTheDocument()
    expect(screen.getByText('Unread')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Edit' }))
    const title = screen.getAllByRole('textbox')[0]!
    await user.clear(title)
    await user.type(title, 'Updated')
    await user.click(screen.getByRole('button', { name: 'Save Changes' }))
    await waitFor(() => expect(update).toHaveBeenCalled())
  })

  it('edits an unmigrated thread through every form field and reports save errors', async () => {
    reviews.reviews = []
    api.get.mockResolvedValue({ id: 1, title: 'Saga', format: 'Comic', issues_remaining: 4, total_issues: null, queue_position: 1, status: 'active', notes: null, collection_id: null })
    update.mockRejectedValueOnce(new Error('save failed'))
    const user = userEvent.setup()
    render(<ThreadDetailView />)
    await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'Edit' }))
    const fields = screen.getAllByRole('textbox')
    await user.clear(fields[0]!)
    await user.type(fields[0]!, 'Renamed')
    await user.selectOptions(screen.getByRole('combobox'), 'Manga')
    const number = screen.getByRole('spinbutton')
    await user.clear(number)
    await user.type(number, '2')
    await user.type(fields[1]!, 'A note')
    await user.click(screen.getByRole('button', { name: 'Save Changes' }))
    await waitFor(() => expect(update).toHaveBeenCalled())
    await user.click(screen.getByRole('button', { name: 'Close modal' }))
  })
})
