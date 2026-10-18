import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CreatorsPage from '../pages/CreatorsPage'
import { useCreatorsList } from '../hooks/useCreatorsList'
import type { CreatorsListState } from '../hooks/useCreatorsList'
import { useCreatorDiscoveries } from '../hooks/useCreatorDiscoveries'
import { useCreatorTeamChemistry } from '../hooks/useCreatorTeamChemistry'
import type { CreatorDiscoveryResponse } from '../types/index'

vi.mock('../hooks/useCreatorsList', () => ({
  useCreatorsList: vi.fn(),
}))

vi.mock('../hooks/useDebounce', () => ({
  useDebounce: <T,>(value: T) => value,
}))

vi.mock('../hooks/useCreatorDiscoveries', () => ({
  useCreatorDiscoveries: vi.fn(),
}))

vi.mock('../hooks/useCreatorTeamChemistry', () => ({
  useCreatorTeamChemistry: vi.fn(),
}))

const mockedList = vi.mocked(useCreatorsList)
const mockedDiscoveries = vi.mocked(useCreatorDiscoveries)
const mockedTeamChemistry = vi.mocked(useCreatorTeamChemistry)

const COMPLETE_COVERAGE = {
  rated_issues_total: 2,
  rated_issues_with_creator_metadata: 2,
  ratings_complete: true,
  read_unrated_issues_total: 0,
  read_unrated_issues_with_creator_metadata: 0,
  read_unrated_complete: true,
  unread_issues_total: 0,
  unread_issues_with_creator_metadata: 0,
  upcoming_complete: true,
}

function baseListState(overrides: Partial<CreatorsListState> = {}): CreatorsListState {
  return {
    items: [],
    total: 0,
    coverage: COMPLETE_COVERAGE,
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

function makeDiscoveries(): CreatorDiscoveryResponse {
  return {
    views: [
      {
        mode: 'consistently_loved',
        title: 'Most consistently loved',
        description: 'High personal average on a meaningful sample.',
        min_sample: 3,
        total: 1,
        truncated: false,
        max_entries: 10,
        entries: [
          {
            canonical_creator_key: 'creator:100',
            display_name: 'Brian K. Vaughan',
            normalized_roles: ['writer'],
            rated_issue_count: 3,
            average_rating: 5.0,
            median_rating: 5.0,
            rating_stddev: 0.0,
            rating_spread: 0.0,
            min_rating: 5.0,
            max_rating: 5.0,
            top_rating_rate: 1.0,
            top_rating_count: 3,
            unread_issue_count: 0,
            read_unrated_issue_count: 0,
            trend_direction: null,
            earlier_average_rating: null,
            recent_average_rating: null,
            trend_delta: null,
            trend_sample_count: 0,
            reasons: [
              {
                metric: 'average_rating',
                label: 'average rating',
                value: 5.0,
                threshold: 4.0,
                comparison: 'gte',
              },
            ],
          },
        ],
      },
    ],
    coverage: {
      rated_issues_total: 3,
      rated_issues_with_creator_metadata: 3,
      ratings_complete: true,
    },
    minimum_reliable_sample: 3,
    max_entries_per_view: 10,
  }
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/creators']}>
      <Routes>
        <Route path="/creators" element={<CreatorsPage />} />
        <Route path="/creators/:creatorKey" element={<div>Creator detail</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  mockedList.mockReturnValue(baseListState())
  mockedTeamChemistry.mockReturnValue({
    data: undefined,
    isPending: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
  })
  mockedDiscoveries.mockReturnValue({
    data: undefined,
    isPending: true,
    isError: false,
    error: null,
    refetch: vi.fn(),
  })
})

describe('CreatorsPage discovery mode', () => {
  it('keeps the browse directory as the default mode', () => {
    renderPage()

    expect(screen.getByRole('button', { name: 'Browse' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'Discover' })).toHaveAttribute('aria-pressed', 'false')
    expect(screen.getByLabelText('Search creators by name')).toBeInTheDocument()
    // Discovery stays inert until its mode is visible.
    expect(mockedDiscoveries).toHaveBeenCalledWith(false)
  })

  it('enables the discovery query only once the discover mode is shown', () => {
    renderPage()

    fireEvent.click(screen.getByRole('button', { name: 'Discover' }))

    expect(mockedDiscoveries).toHaveBeenLastCalledWith(true)
    expect(screen.queryByLabelText('Search creators by name')).not.toBeInTheDocument()
    expect(screen.getByLabelText('Loading discoveries')).toBeInTheDocument()
  })

  it('renders discovery views and navigates to a creator detail page', () => {
    mockedDiscoveries.mockReturnValue({
      data: makeDiscoveries(),
      isPending: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    })

    renderPage()
    fireEvent.click(screen.getByRole('button', { name: 'Discover' }))

    expect(screen.getByRole('heading', { name: 'Discover your taste' })).toBeInTheDocument()
    expect(screen.getByText('average rating 5 ≥ 4')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('link', { name: 'Brian K. Vaughan' }))
    expect(screen.getByText('Creator detail')).toBeInTheDocument()
  })

  it('explains a failed discovery load with a recovery action', () => {
    const refetch = vi.fn()
    mockedDiscoveries.mockReturnValue({
      data: undefined,
      isPending: false,
      isError: true,
      error: new Error('boom'),
      refetch,
    })

    renderPage()
    fireEvent.click(screen.getByRole('button', { name: 'Discover' }))

    expect(screen.getByRole('alert')).toHaveTextContent('Could not load taste discoveries')
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(refetch).toHaveBeenCalled()
  })

  it('restores the plain directory when returning to browse', () => {
    mockedDiscoveries.mockReturnValue({
      data: makeDiscoveries(),
      isPending: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    })

    renderPage()
    fireEvent.click(screen.getByRole('button', { name: 'Discover' }))
    expect(screen.getByRole('heading', { name: 'Discover your taste' })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Browse' }))

    expect(screen.getByLabelText('Search creators by name')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Discover your taste' })).not.toBeInTheDocument()
  })
})
