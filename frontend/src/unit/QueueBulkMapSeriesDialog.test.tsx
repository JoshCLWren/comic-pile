import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import QueueBulkMapSeriesDialog from '../../components/QueueBulkMapSeriesDialog'

// Mock the hooks and API
jest.mock('../../hooks/useQueueSeriesMapping')
jest.mock('../../services/api-comicvine')
jest.mock('../../services/api-series-mapping')

const mockUseQueueSeriesMapping = require('../../hooks/useQueueSeriesMapping')
const mockComicVineApi = require('../../services/api-comicvine')
const mockApiSeriesMapping = require('../../services/api-series-mapping')

describe('QueueBulkMapSeriesDialog', () => {
  const defaultProps = {
    isOpen: true,
    threadIds: [1, 2, 3],
    threadTitles: ['Batman', 'Superman', 'Wonder Woman'],
    onClose: jest.fn(),
    onMapped: jest.fn(),
  }

  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })

  beforeEach(() => {
    jest.clearAllMocks()
    
    // Mock the API responses
    mockComicVineApi.default.searchSeries.mockResolvedValue({
      results: [
        {
          comicvine_volume_id: '123',
          name: 'Batman (2016)',
          publisher: 'DC Comics',
          start_year: 2016,
          issue_count: 100,
          site_detail_url: 'https://comicvine.gamespot.com/batman-2016/4050-58512/',
          image: { super_url: 'https://example.com/image.jpg' },
        },
      ],
      has_more: false,
      next_offset: null,
    })

    mockUseQueueSeriesMapping.useQueueMappingOriginIssue.mockReturnValue({
      data: { id: 1 },
      isSuccess: true,
      isError: false,
    })

    mockUseQueueSeriesMapping.useQueueSeriesMappingPreview.mockReturnValue({
      data: {
        preview_token: 'token123',
        scope: {
          status: 'available',
          scope_key: 'key123',
          origin_issue_id: 1,
          series_label: 'Batman',
          basis: 'exact_match',
        },
        provider_series: {
          id: '123',
          name: 'Batman (2016)',
          publisher: 'DC Comics',
          start_year: 2016,
          count_of_issues: 100,
          site_detail_url: 'https://comicvine.gamespot.com/batman-2016/4050-58512/',
          image: { super_url: 'https://example.com/image.jpg' },
        },
        counts: {
          already_confirmed: 0,
          safe_exact_match: 2,
          needs_review_ambiguous: 0,
          needs_review_conflict: 0,
          unresolved: 0,
          excluded_special: 0,
        },
        rows: [
          {
            row_id: 'row1',
            issue_id: 1,
            issue_number: '#1',
            title: 'Batman: The First Night',
            classification: 'safe_exact_match',
            thread_id: 1,
            thread_title: 'Batman',
            current_mapping_status: null,
            proposed_mapping: true,
            default_selected: true,
            reason: null,
          },
          {
            row_id: 'row2',
            issue_id: 2,
            issue_number: '#2',
            title: 'Batman: The Second Night',
            classification: 'safe_exact_match',
            thread_id: 1,
            thread_title: 'Batman',
            current_mapping_status: null,
            proposed_mapping: true,
            default_selected: true,
            reason: null,
          },
        ],
        issued_at: Date.now(),
        expires_at: Date.now() + 3600000,
      },
      isSuccess: true,
      isError: false,
      isPending: false,
      isFetching: false,
    })

    mockUseQueueSeriesMapping.useQueueSeriesMappingCommit.mockReturnValue({
      mutate: jest.fn().mockResolvedValue({
        idempotency_key: 'key123',
        confirmed_issue_ids: [1, 2],
        already_confirmed_issue_ids: [],
        needs_review_issue_ids: [],
        hydration_queued_issue_ids: [],
        series_mapping: {
          provider: 'comicvine',
          external_id: '123',
          status: 'confirmed',
          evidence_source: 'user_confirmation',
        },
      }),
      isError: false,
      isPending: false,
    })

    mockApiSeriesMapping.bulkApprovableSeriesMappingRows.mockReturnValue([
      {
        row_id: 'row1',
        issue_id: 1,
        issue_number: '#1',
        title: 'Batman: The First Night',
        classification: 'safe_exact_match',
        thread_id: 1,
        thread_title: 'Batman',
        current_mapping_status: null,
        proposed_mapping: true,
        default_selected: true,
        reason: null,
      },
      {
        row_id: 'row2',
        issue_id: 2,
        issue_number: '#2',
        title: 'Batman: The Second Night',
        classification: 'safe_exact_match',
        thread_id: 1,
        thread_title: 'Batman',
        current_mapping_status: null,
        proposed_mapping: true,
        default_selected: true,
        reason: null,
      },
    ])

    mockApiSeriesMapping.isOwnedSeriesMappingRow.mockReturnValue(true)
  })

  it('renders when open', () => {
    render(
      <QueryClientProvider client={queryClient}>
        <QueueBulkMapSeriesDialog {...defaultProps} />
      </QueryClientProvider>
    )

    expect(screen.getByText('Map Series')).toBeInTheDocument()
    expect(screen.getByText('Batman')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('Search ComicVine volumes')).toBeInTheDocument()
  })

  it('shows progress indicator', () => {
    render(
      <QueryClientProvider client={queryClient}>
        <QueueBulkMapSeriesDialog {...defaultProps} />
      </QueryClientProvider>
    )

    expect(screen.getByText('1 of 3')).toBeInTheDocument()
  })

  it('allows searching for series', async () => {
    render(
      <QueryClientProvider client={queryClient}>
        <QueueBulkMapSeriesDialog {...defaultProps} />
      </QueryClientProvider>
    )

    const searchInput = screen.getByPlaceholderText('Search ComicVine volumes')
    fireEvent.change(searchInput, { target: { value: 'Batman' } })

    await waitFor(() => {
      expect(screen.getByText('Batman (2016)')).toBeInTheDocument()
    })
  })

  it('allows selecting a series and previewing mapping', async () => {
    render(
      <QueryClientProvider client={queryClient}>
        <QueueBulkMapSeriesDialog {...defaultProps} />
      </QueryClientProvider>
    )

    // Search for series
    const searchInput = screen.getByPlaceholderText('Search ComicVine volumes')
    fireEvent.change(searchInput, { target: { value: 'Batman' } })

    await waitFor(() => {
      expect(screen.getByText('Batman (2016)')).toBeInTheDocument()
    })

    // Select the series
    fireEvent.click(screen.getByText('Batman (2016)'))

    // Should show preview
    await waitFor(() => {
      expect(screen.getByText('Review Series Mapping')).toBeInTheDocument()
      expect(screen.getByText('2 issues mapped to Batman (2016)')).toBeInTheDocument()
    })
  })

  it('allows committing the mapping', async () => {
    render(
      <QueryClientProvider client={queryClient}>
        <QueueBulkMapSeriesDialog {...defaultProps} />
      </QueryClientProvider>
    )

    // Search for series
    const searchInput = screen.getByPlaceholderText('Search ComicVine volumes')
    fireEvent.change(searchInput, { target: { value: 'Batman' } })

    await waitFor(() => {
      expect(screen.getByText('Batman (2016)')).toBeInTheDocument()
    })

    // Select the series
    fireEvent.click(screen.getByText('Batman (2016)'))

    // Wait for preview to load
    await waitFor(() => {
      expect(screen.getByText('Review Series Mapping')).toBeInTheDocument()
    })

    // Commit the mapping
    fireEvent.click(screen.getByText('Map 2 issues'))

    // Should move to next thread
    await waitFor(() => {
      expect(screen.getByText('Map Series')).toBeInTheDocument()
      expect(screen.getByText('Superman')).toBeInTheDocument()
    })
  })

  it('shows results when all threads are processed', async () => {
    render(
      <QueryClientProvider client={queryClient}>
        <QueueBulkMapSeriesDialog {...defaultProps} />
      </QueryClientProvider>
    )

    // Process all threads (mock the completion)
    for (let i = 0; i < 3; i++) {
      // Search for series
      const searchInput = screen.getByPlaceholderText('Search ComicVine volumes')
      fireEvent.change(searchInput, { target: { value: defaultProps.threadTitles[i] } })

      await waitFor(() => {
        expect(screen.getByText(defaultProps.threadTitles[i])).toBeInTheDocument()
      })

      // Select the series
      fireEvent.click(screen.getByText(defaultProps.threadTitles[i]))

      // Wait for preview to load
      await waitFor(() => {
        expect(screen.getByText('Review Series Mapping')).toBeInTheDocument()
      })

      // Commit the mapping
      fireEvent.click(screen.getByText('Map 2 issues'))

      // Wait for next thread or results
      await waitFor(() => {
        if (i < 2) {
          expect(screen.getByText('Map Series')).toBeInTheDocument()
          expect(screen.getByText(defaultProps.threadTitles[i + 1])).toBeInTheDocument()
        }
      })
    }

    // Should show results
    await waitFor(() => {
      expect(screen.getByText('Mapping complete for 3 series')).toBeInTheDocument()
      expect(screen.getByText('3 series successfully mapped with 6 issues')).toBeInTheDocument()
    })
  })

  it('can be cancelled', () => {
    render(
      <QueryClientProvider client={queryClient}>
        <QueueBulkMapSeriesDialog {...defaultProps} />
      </QueryClientProvider>
    )

    fireEvent.click(screen.getByText('Done'))

    expect(defaultProps.onClose).toHaveBeenCalled()
  })

  it('handles search errors', async () => {
    mockComicVineApi.default.searchSeries.mockRejectedValue(new Error('Search failed'))

    render(
      <QueryClientProvider client={queryClient}>
        <QueueBulkMapSeriesDialog {...defaultProps} />
      </QueryClientProvider>
    )

    const searchInput = screen.getByPlaceholderText('Search ComicVine volumes')
    fireEvent.change(searchInput, { target: { value: 'Invalid Search' } })

    await waitFor(() => {
      expect(screen.getByText('Failed to search ComicVine. Please try again.')).toBeInTheDocument()
    })
  })

  it('handles preview errors', async () => {
    mockUseQueueSeriesMapping.useQueueSeriesMappingPreview.mockReturnValue({
      data: null,
      isSuccess: false,
      isError: true,
      isPending: false,
      isFetching: false,
    })

    render(
      <QueryClientProvider client={queryClient}>
        <QueueBulkMapSeriesDialog {...defaultProps} />
      </QueryClientProvider>
    )

    // Search for series
    const searchInput = screen.getByPlaceholderText('Search ComicVine volumes')
    fireEvent.change(searchInput, { target: { value: 'Batman' } })

    await waitFor(() => {
      expect(screen.getByText('Batman (2016)')).toBeInTheDocument()
    })

    // Select the series
    fireEvent.click(screen.getByText('Batman (2016)'))

    // Should show error
    await waitFor(() => {
      expect(screen.getByText('The mapping plan could not be loaded. Nothing was changed.')).toBeInTheDocument()
    })
  })
})