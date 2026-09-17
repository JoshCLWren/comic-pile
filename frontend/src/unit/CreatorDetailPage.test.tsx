import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CreatorDetailPage from '../pages/CreatorDetailPage'
import { useCreatorDetail } from '../hooks/useCreatorDetail'
import type { CreatorDetailState } from '../hooks/useCreatorDetail'

vi.mock('../hooks/useCreatorDetail', () => ({
  useCreatorDetail: vi.fn(),
}))

const mockedHook = vi.mocked(useCreatorDetail)

function baseState(overrides: Partial<CreatorDetailState> = {}): CreatorDetailState {
  return {
    summary: {
      canonical_creator_key: 'creator:7',
      display_name: 'Test Creator',
      normalized_roles: ['writer', 'artist'],
      average_rating: 4.5,
      ratings_count: 2,
      read_unrated_count: 1,
      upcoming_count: 3,
    },
    coverage: {
      rated_issues_total: 2,
      rated_issues_with_creator_metadata: 2,
      ratings_complete: true,
      read_unrated_issues_total: 1,
      read_unrated_issues_with_creator_metadata: 1,
      read_unrated_complete: true,
      unread_issues_total: 3,
      unread_issues_with_creator_metadata: 3,
      upcoming_complete: true,
    },
    roleStats: [
      { role: 'writer', issue_count: 5, average_rating: 4.5 },
      { role: 'cover', issue_count: 1, average_rating: null },
    ],
    ratedIssues: [
      {
        issue_id: 11,
        issue_number: '1',
        thread_id: 1,
        thread_title: 'Series A',
        status: 'read',
        roles: ['writer'],
        effective_rating: 5,
        rating_timestamp: '2026-01-02T00:00:00Z',
        sort_key: '11',
      },
    ],
    readUnratedIssues: [
      {
        issue_id: 13,
        issue_number: '3',
        thread_id: 2,
        thread_title: 'Series B',
        status: 'read',
        roles: ['artist'],
        effective_rating: null,
        rating_timestamp: null,
        sort_key: '13',
      },
    ],
    upcomingIssues: [
      {
        issue_id: 14,
        issue_number: '4',
        thread_id: 3,
        thread_title: 'Series C',
        status: 'unread',
        roles: ['writer'],
        effective_rating: null,
        rating_timestamp: null,
        sort_key: '0000001:0000004:14',
      },
    ],
    isPending: false,
    isFetchingMore: false,
    isError: false,
    error: null,
    hasMore: false,
    loadMore: vi.fn(),
    refetch: vi.fn(),
    ...overrides,
  }
}

function renderAt(key: string) {
  return render(
    <MemoryRouter initialEntries={[`/creators/${encodeURIComponent(key)}`]}>
      <Routes>
        <Route path="/creators/:creatorKey" element={<CreatorDetailPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  mockedHook.mockReturnValue(baseState())
})

describe('CreatorDetailPage', () => {
  it('renders summary with average plus sample size and all sections', () => {
    renderAt('creator:7')

    expect(screen.getByRole('heading', { name: 'Test Creator' })).toBeInTheDocument()
    expect(screen.getByLabelText('Average rating 4.5 out of 5 from 2 ratings')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Roles' })).toBeInTheDocument()
    expect(screen.getByText('cover')).toBeInTheDocument()
    // The writer role appears both in the role breakdown and on issue rows.
    expect(screen.getAllByText('writer').length).toBeGreaterThanOrEqual(2)
    expect(screen.getByRole('heading', { name: /Rated/ })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /Upcoming in ComicPile/ })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /Read, not rated/ })).toBeInTheDocument()
    // Issue rows link into the existing thread route.
    const ratedLink = screen.getByRole('link', { name: /Series A/ })
    expect(ratedLink.getAttribute('href')).toBe('/thread/1')
  })

  it('shows a neutral state instead of 0 stars for unrated creators', () => {
    mockedHook.mockReturnValue(
      baseState({
        summary: { ...baseState().summary!, average_rating: null, ratings_count: 0 },
        ratedIssues: [],
      }),
    )
    renderAt('creator:7')

    expect(screen.getByText('No ratings yet')).toBeInTheDocument()
    expect(screen.queryByText(/0★/)).not.toBeInTheDocument()
    expect(screen.getByText('Nothing rated for this creator yet.')).toBeInTheDocument()
  })

  it('communicates partial coverage as lower-bound results', () => {
    mockedHook.mockReturnValue(
      baseState({
        coverage: { ...baseState().coverage!, ratings_complete: false, upcoming_complete: false },
      }),
    )
    renderAt('creator:7')

    expect(screen.getByText(/lower bounds, not exhaustive totals/)).toBeInTheDocument()
    expect(screen.getByText(/Partial list: some rated issues/)).toBeInTheDocument()
  })

  it('shows not-found behavior for invalid keys without fetching', () => {
    renderAt('Stan Lee')

    expect(mockedHook).toHaveBeenCalledWith(null)
    expect(screen.getByRole('heading', { name: 'Creator not found' })).toBeInTheDocument()
  })

  it('shows a recoverable error with retry on failure', () => {
    const refetch = vi.fn()
    mockedHook.mockReturnValue(baseState({ isError: true, error: new Error('down'), summary: null, coverage: null, refetch }))
    renderAt('creator:7')

    expect(screen.getByRole('heading', { name: 'Could not load creator' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(refetch).toHaveBeenCalledTimes(1)
  })

  it('offers load-more pagination when the backend reports a cursor', () => {
    const loadMore = vi.fn().mockResolvedValue(undefined)
    mockedHook.mockReturnValue(baseState({ hasMore: true, loadMore }))
    renderAt('creator:7')

    fireEvent.click(screen.getByRole('button', { name: 'Load more' }))
    expect(loadMore).toHaveBeenCalledTimes(1)
  })

  it('keeps the shell stable while the first page loads', () => {
    mockedHook.mockReturnValue(baseState({ isPending: true }))
    renderAt('creator:7')

    expect(screen.getByLabelText('Loading creator details')).toBeInTheDocument()
  })

  it('shows the not-found copy for 404 responses without a retry', () => {
    mockedHook.mockReturnValue(
      baseState({ isError: true, error: { response: { status: 404 } }, summary: null, coverage: null }),
    )
    renderAt('creator:7')

    expect(screen.getByRole('heading', { name: 'Creator not found' })).toBeInTheDocument()
    expect(screen.getByText('This creator is not in your library.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Try again' })).not.toBeInTheDocument()
  })

  it('omits the read-not-rated section and counter when there is nothing to show', () => {
    mockedHook.mockReturnValue(
      baseState({ readUnratedIssues: [], summary: { ...baseState().summary!, read_unrated_count: 0 } }),
    )
    renderAt('creator:7')

    expect(screen.queryByRole('heading', { name: /Read, not rated/ })).not.toBeInTheDocument()
    expect(screen.queryByText('Read, not rated')).not.toBeInTheDocument()
  })

  it('renders issue rows without roles or dates when metadata is absent', () => {
    mockedHook.mockReturnValue(
      baseState({
        upcomingIssues: [
          {
            issue_id: 14,
            issue_number: '4',
            thread_id: 3,
            thread_title: 'Series C',
            status: 'unread',
            roles: [],
            effective_rating: null,
            rating_timestamp: null,
            sort_key: '0000001:0000004:14',
          },
        ],
      }),
    )
    renderAt('creator:7')

    expect(screen.getByRole('link', { name: /Series C #4/ })).toBeInTheDocument()
  })

  it('hides the role breakdown when the backend reports no roles', () => {
    mockedHook.mockReturnValue(baseState({ roleStats: [] }))
    renderAt('creator:7')

    expect(screen.queryByRole('heading', { name: 'Roles' })).not.toBeInTheDocument()
  })

  it('flags read-but-unrated coverage as partial when metadata is incomplete', () => {
    mockedHook.mockReturnValue(
      baseState({ coverage: { ...baseState().coverage!, read_unrated_complete: false } }),
    )
    renderAt('creator:7')

    expect(screen.getByRole('note')).toHaveTextContent(/Read-but-unrated results are partial/)
    expect(screen.getByText(/Partial list: some read issues are still missing creator metadata/)).toBeInTheDocument()
  })

  it('retains loaded content and offers retry after a load-more failure', () => {
    const loadMore = vi.fn().mockResolvedValue(undefined)
    mockedHook.mockReturnValue(baseState({
      isError: true,
      error: new Error('next page failed'),
      hasMore: true,
      loadMore,
    }))
    renderAt('creator:7')

    expect(screen.getByRole('heading', { name: 'Test Creator' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Series A/ })).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('Could not load more')
    expect(screen.queryByRole('heading', { name: 'Could not load creator' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Load more' }))
    expect(loadMore).toHaveBeenCalledTimes(1)
  })

  it('treats a percent sign in an invalid key as not found rather than crashing', () => {
    renderAt('creator:%')

    expect(mockedHook).toHaveBeenCalledWith(null)
    expect(screen.getByRole('heading', { name: 'Creator not found' })).toBeInTheDocument()
  })
})
