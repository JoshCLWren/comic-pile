import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CreatorsPage from '../pages/CreatorsPage'
import { useQuery } from '@tanstack/react-query'
import type { CreatorListResponse } from '../services/api-creators'

vi.mock('@tanstack/react-query', () => ({
  useQuery: vi.fn(),
}))

vi.mock('../services/api-creators', () => ({
  creatorsApi: {
    getList: vi.fn(),
  },
  type CreatorListResponse: Object,
}))

const mockedUseQuery = vi.mocked(useQuery)
const mockedCreatorsApi = vi.mocked(require('../services/api-creators').creatorsApi)

function mockListResponse(overrides: Partial<CreatorListResponse> = {}): CreatorListResponse {
  return {
    items: [
      {
        canonical_creator_key: 'creator:7',
        display_name: 'Test Creator',
        normalized_roles: ['writer'],
        average_rating: 4.5,
        ratings_count: 2,
      },
      {
        canonical_creator_key: 'creator:12',
        display_name: 'Another Creator',
        normalized_roles: ['artist'],
        average_rating: 3.8,
        ratings_count: 5,
      },
    ],
    total: 2,
    limit: 20,
    offset: 0,
    coverage: {
      rated_issues_total: 7,
      rated_issues_with_creator_metadata: 7,
      ratings_complete: true,
      read_unrated_issues_total: 3,
      read_unrated_issues_with_creator_metadata: 3,
      read_unrated_complete: true,
      unread_issues_total: 10,
      unread_issues_with_creator_metadata: 10,
      upcoming_complete: true,
    },
    ...overrides,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('CreatorsPage', () => {
  it('renders loading state', () => {
    mockedUseQuery.mockReturnValue({
      data: null,
      isPending: true,
      isLoadingMore: false,
      hasMore: false,
      loadMore: vi.fn(),
      error: null,
    })

    render(
      <MemoryRouter initialEntries={['/creators']}>
        <Routes>
          <Route path="/creators" element={<CreatorsPage />} />
        </Routes>
      </MemoryRouter>
    )

    expect(screen.getByText('Loading creators...')).toBeInTheDocument()
  })

  it('renders error state', () => {
    mockedUseQuery.mockReturnValue({
      data: null,
      isPending: false,
      isLoadingMore: false,
      hasMore: false,
      loadMore: vi.fn(),
      error: new Error('Failed to load'),
    })

    render(
      <MemoryRouter initialEntries={['/creators']}>
        <Routes>
          <Route path="/creators" element={<CreatorsPage />} />
        </Routes>
      </MemoryRouter>
    )

    expect(screen.getByText('Failed to load creators')).toBeInTheDocument()
  })

  it('renders empty state when no creators', () => {
    mockedUseQuery.mockReturnValue({
      data: mockListResponse({ items: [], total: 0 }),
      isPending: false,
      isLoadingMore: false,
      hasMore: false,
      loadMore: vi.fn(),
      error: null,
    })

    render(
      <MemoryRouter initialEntries={['/creators']}>
        <Routes>
          <Route path="/creators" element={<CreatorsPage />} />
        </Routes>
      </MemoryRouter>
    )

    expect(screen.getByText("You haven't rated any creators yet.")).toBeInTheDocument()
  })

  it('renders empty state when search yields no results', () => {
    mockedUseQuery.mockReturnValue({
      data: mockListResponse({ items: [], total: 0 }),
      isPending: false,
      isLoadingMore: false,
      hasMore: false,
      loadMore: vi.fn(),
      error: null,
    })

    render(
      <MemoryRouter initialEntries={['/creators']}>
        <Routes>
          <Route path="/creators" element={<CreatorsPage />} />
        </Routes>
      </MemoryRouter>
    )

    const searchInput = screen.getByPlaceholderText('Search creators...')
    fireEvent.change(searchInput, { target: { value: 'Nonexistent' } })
    
    expect(screen.getByText('No creators found matching your search.')).toBeInTheDocument()
  })

  it('renders creator list with data', () => {
    const mockData = mockListResponse()
    mockedUseQuery.mockReturnValue({
      data: mockData,
      isPending: false,
      isLoadingMore: false,
      hasMore: false,
      loadMore: vi.fn(),
      error: null,
    })

    render(
      <MemoryRouter initialEntries={['/creators']}>
        <Routes>
          <Route path="/creators" element={<CreatorsPage />} />
        </Routes>
      </MemoryRouter>
    )

    expect(screen.getByText('Creators')).toBeInTheDocument()
    expect(screen.getByText('Browse your rated creators (2 total)')).toBeInTheDocument()
    
    // Check first creator
    expect(screen.getByText('Test Creator')).toBeInTheDocument()
    expect(screen.getByText('2 issues')).toBeInTheDocument()
    expect(screen.getByText('★ 4.5')).toBeInTheDocument()
    expect(screen.getByText('writer')).toBeInTheDocument()
    
    // Check second creator
    expect(screen.getByText('Another Creator')).toBeInTheDocument()
    expect(screen.getByText('5 issues')).toBeInTheDocument()
    expect(screen.getByText('★ 3.8')).toBeInTheDocument()
    expect(screen.getByText('artist')).toBeInTheDocument()
  })

  it('handles search input', () => {
    const mockData = mockListResponse()
    mockedUseQuery.mockReturnValue({
      data: mockData,
      isPending: false,
      isLoadingMore: false,
      hasMore: false,
      loadMore: vi.fn(),
      error: null,
    })

    render(
      <MemoryRouter initialEntries={['/creators']}>
        <Routes>
          <Route path="/creators" element={<CreatorsPage />} />
        </Routes>
      </MemoryRouter>
    )

    const searchInput = screen.getByPlaceholderText('Search creators...')
    fireEvent.change(searchInput, { target: { value: 'Test' } })
    
    // Should reset to first page when searching
    expect(searchInput).toHaveValue('Test')
  })

  it('handles sorting changes', () => {
    const mockData = mockListResponse()
    mockedUseQuery.mockReturnValue({
      data: mockData,
      isPending: false,
      isLoadingMore: false,
      hasMore: false,
      loadMore: vi.fn(),
      error: null,
    })

    render(
      <MemoryRouter initialEntries={['/creators']}>
        <Routes>
          <Route path="/creators" element={<CreatorsPage />} />
        </Routes>
      </MemoryRouter>
    )

    // Test sorting by ratings count
    const ratingsCountButton = screen.getByText('Most Rated')
    fireEvent.click(ratingsCountButton)
    
    // Test sorting by average rating
    const averageRatingButton = screen.getByText('Highest Rated')
    fireEvent.click(averageRatingButton)
    
    // Test sorting by name
    const nameButton = screen.getByText('Name')
    fireEvent.click(nameButton)
  })

  it('navigates to creator detail when clicking creator', () => {
    const mockData = mockListResponse()
    mockedUseQuery.mockReturnValue({
      data: mockData,
      isPending: false,
      isLoadingMore: false,
      hasMore: false,
      loadMore: vi.fn(),
      error: null,
    })

    render(
      <MemoryRouter initialEntries={['/creators']}>
        <Routes>
          <Route path="/creators" element={<CreatorsPage />} />
          <Route path="/creators/:creatorKey" element={<div>Creator Detail</div>} />
        </Routes>
      </MemoryRouter>
    )

    const creatorLink = screen.getByText('Test Creator').closest('a')
    expect(creatorLink).toHaveAttribute('href', '/creators/creator%3A7')
  })

  it('shows load more button when there are more results', () => {
    const mockData = mockListResponse({ total: 50 })
    mockedUseQuery.mockReturnValue({
      data: mockData,
      isPending: false,
      isLoadingMore: false,
      hasMore: true,
      loadMore: vi.fn(),
      error: null,
    })

    render(
      <MemoryRouter initialEntries={['/creators']}>
        <Routes>
          <Route path="/creators" element={<CreatorsPage />} />
        </Routes>
      </MemoryRouter>
    )

    expect(screen.getByText('Load More')).toBeInTheDocument()
  })

  it('handles load more click', () => {
    const mockData = mockListResponse({ total: 50 })
    const loadMoreMock = vi.fn()
    mockedUseQuery.mockReturnValue({
      data: mockData,
      isPending: false,
      isLoadingMore: false,
      hasMore: true,
      loadMore: loadMoreMock,
      error: null,
    })

    render(
      <MemoryRouter initialEntries={['/creators']}>
        <Routes>
          <Route path="/creators" element={<CreatorsPage />} />
        </Routes>
      </MemoryRouter>
    )

    const loadMoreButton = screen.getByText('Load More')
    fireEvent.click(loadMoreButton)
    
    expect(loadMoreMock).toHaveBeenCalled()
  })

  it('shows loading state on load more', () => {
    const mockData = mockListResponse({ total: 50 })
    mockedUseQuery.mockReturnValue({
      data: mockData,
      isPending: false,
      isLoadingMore: true,
      hasMore: true,
      loadMore: vi.fn(),
      error: null,
    })

    render(
      <MemoryRouter initialEntries={['/creators']}>
        <Routes>
          <Route path="/creators" element={<CreatorsPage />} />
        </Routes>
      </MemoryRouter>
    )

    expect(screen.getByText('Loading...')).toBeInTheDocument()
    expect(screen.queryByText('Load More')).not.toBeInTheDocument()
  })

  it('shows page info when there are multiple pages', () => {
    const mockData = mockListResponse({ total: 50, limit: 20, offset: 20 })
    mockedUseQuery.mockReturnValue({
      data: mockData,
      isPending: false,
      isLoadingMore: false,
      hasMore: false,
      loadMore: vi.fn(),
      error: null,
    })

    render(
      <MemoryRouter initialEntries={['/creators']}>
        <Routes>
          <Route path="/creators" element={<CreatorsPage />} />
        </Routes>
      </MemoryRouter>
    )

    expect(screen.getByText('Page 2 of 3')).toBeInTheDocument()
  })
})