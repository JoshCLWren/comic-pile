import { render, screen, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CreatorComparisonPage from '../pages/CreatorComparisonPage'
import { useCreatorComparison } from '../hooks/useCreatorComparison'
import type { CreatorComparisonItem, CreatorComparisonResponse } from '../types/index'

vi.mock('../hooks/useCreatorComparison', () => ({
  useCreatorComparison: vi.fn(),
}))

const mockedHook = vi.mocked(useCreatorComparison)

type HookResult = ReturnType<typeof useCreatorComparison>

const COMPLETE_COVERAGE = {
  rated_issues_total: 9,
  rated_issues_with_creator_metadata: 9,
  ratings_complete: true,
  read_unrated_issues_total: 1,
  read_unrated_issues_with_creator_metadata: 1,
  read_unrated_complete: true,
  unread_issues_total: 2,
  unread_issues_with_creator_metadata: 2,
  upcoming_complete: true,
}

function makeItem(overrides: Partial<CreatorComparisonItem> & { canonical_creator_key: string }): CreatorComparisonItem {
  return {
    display_name: 'A Creator',
    normalized_roles: ['writer'],
    average_rating: 4.5,
    median_rating: 4.5,
    ratings_count: 4,
    rating_distribution: { '5': 2, '4': 2 },
    top_rating_rate: 0.5,
    role_stats: [{ role: 'writer', issue_count: 4, average_rating: 4.5 }],
    strongest_series: [{ thread_id: 1, thread_title: 'Saga', issue_count: 3, average_rating: 4.7 }],
    unread_upcoming_count: 2,
    read_unrated_count: 1,
    insufficient_data: false,
    ...overrides,
  }
}

function makeResponse(overrides: Partial<CreatorComparisonResponse> = {}): CreatorComparisonResponse {
  return {
    comparisons: {},
    coverage: COMPLETE_COVERAGE,
    insufficient_data_keys: [],
    ...overrides,
  }
}

function baseHook(overrides: Partial<HookResult> = {}): HookResult {
  return {
    data: undefined,
    isPending: false,
    isError: false,
    error: null,
    ...overrides,
  }
}

function renderAt(keysQuery: string | null) {
  const entry = keysQuery == null ? '/creators/compare' : `/creators/compare?keys=${keysQuery}`
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <Routes>
        <Route path="/creators/compare" element={<CreatorComparisonPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  mockedHook.mockReturnValue(baseHook())
})

describe('CreatorComparisonPage', () => {
  it('prompts for a 2-4 creator selection instead of fetching', () => {
    for (const keys of [null, 'creator:7', 'creator:1,creator:2,creator:3,creator:4,creator:5']) {
      const { unmount } = renderAt(keys)
      expect(screen.getByRole('heading', { name: 'Creator Comparison' })).toBeInTheDocument()
      expect(screen.getByText(/Select 2 to 4 creators from the/)).toBeInTheDocument()
      unmount()
    }
    expect(mockedHook).toHaveBeenCalledWith(null)
  })

  it('renders loading skeletons while the comparison is pending', () => {
    mockedHook.mockReturnValue(baseHook({ isPending: true }))

    renderAt('creator:7,creator:12')

    expect(screen.getByLabelText('Loading creator comparison')).toBeInTheDocument()
  })

  it('renders a recoverable error that preserves library state', () => {
    mockedHook.mockReturnValue(baseHook({ isError: true, error: new Error('boom') }))

    renderAt('creator:7,creator:12')

    expect(screen.getByRole('heading', { name: 'Could not load comparison' })).toBeInTheDocument()
    expect(screen.getByText('The comparison failed to load. Your data is unchanged.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Back to Creators' })).toBeInTheDocument()
  })

  it('explains unknown creators without offering a retry', () => {
    const notFound = Object.assign(new Error('missing'), { response: { status: 404 } })
    mockedHook.mockReturnValue(baseHook({ isError: true, error: notFound }))

    renderAt('creator:7,creator:999')

    expect(screen.getByRole('heading', { name: 'Creators not found' })).toBeInTheDocument()
    expect(screen.getByText('One or more creators are not in your library.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Try again' })).not.toBeInTheDocument()
  })

  it('renders side-by-side personal metrics with sample sizes and navigable series', () => {
    mockedHook.mockReturnValue(
      baseHook({
        data: makeResponse({
          comparisons: {
            'creator:7': makeItem({
              canonical_creator_key: 'creator:7',
              display_name: 'Brian K. Vaughan',
              normalized_roles: ['writer', 'editor'],
              rating_distribution: { '5': 2, '4.5': 1, '4': 1 },
            }),
            'creator:12': makeItem({
              canonical_creator_key: 'creator:12',
              display_name: 'Steve McNiven',
              average_rating: 3.8,
              median_rating: 4,
              ratings_count: 5,
              top_rating_rate: 0.2,
              strongest_series: [
                { thread_id: 2, thread_title: 'Old Man Logan', issue_count: 2, average_rating: 3.5 },
              ],
              read_unrated_count: 0,
            }),
          },
        }),
      }),
    )

    renderAt('creator:7,creator:12')

    expect(screen.getByText('Comparing 2 creators')).toBeInTheDocument()
    expect(screen.getByLabelText('Average rating 4.5 out of 5 from 4 ratings')).toBeInTheDocument()
    expect(screen.getByLabelText('Average rating 3.8 out of 5 from 5 ratings')).toBeInTheDocument()
    expect(screen.getByText('writer, editor')).toBeInTheDocument()
    expect(screen.getByText('50.0%')).toBeInTheDocument()
    expect(screen.getByText('20.0%')).toBeInTheDocument()
    expect(screen.getByText('Read, not rated')).toBeInTheDocument()

    const creatorLink = screen.getByRole('link', { name: 'Brian K. Vaughan' })
    expect(creatorLink).toHaveAttribute('href', '/creators/creator%3A7')
    const seriesLink = screen.getByRole('link', { name: /Saga/ })
    expect(seriesLink).toHaveAttribute('href', '/thread/1')

    const distributions = screen.getAllByRole('img', { name: 'Rating distribution' })
    expect(within(distributions[0]).getByText('4.5★')).toBeInTheDocument()
  })

  it('marks thin samples and partial metadata explicitly instead of implying totals', () => {
    mockedHook.mockReturnValue(
      baseHook({
        data: makeResponse({
          comparisons: {
            'creator:12': makeItem({
              canonical_creator_key: 'creator:12',
              display_name: 'Steve McNiven',
              ratings_count: 2,
              insufficient_data: true,
            }),
          },
          coverage: { ...COMPLETE_COVERAGE, ratings_complete: false },
          insufficient_data_keys: ['creator:12'],
        }),
      }),
    )

    renderAt('creator:7,creator:12')

    expect(screen.getByText('Comparing 1 creator')).toBeInTheDocument()
    expect(screen.getByText('Insufficient data')).toBeInTheDocument()
    expect(screen.getByText(/less reliable/)).toBeInTheDocument()
    expect(screen.getByText(/Affected: 12/)).toBeInTheDocument()
    expect(screen.getByRole('note')).toHaveTextContent('Counts shown are lower bounds.')
  })

  it('renders unrated and keyless creators without manufacturing equivalence', () => {
    mockedHook.mockReturnValue(
      baseHook({
        data: makeResponse({
          comparisons: {
            mystery: makeItem({
              canonical_creator_key: 'mystery',
              display_name: 'Mystery Writer',
              normalized_roles: [],
              average_rating: null,
              median_rating: null,
              ratings_count: 0,
              rating_distribution: {},
              top_rating_rate: null,
              role_stats: [{ role: 'artist', issue_count: 2, average_rating: null }],
              strongest_series: [
                { thread_id: 9, thread_title: 'Old Man Logan', issue_count: 2, average_rating: null },
              ],
              unread_upcoming_count: 0,
              read_unrated_count: 0,
            }),
          },
        }),
      }),
    )

    renderAt('creator:7,mystery')

    expect(screen.getByRole('heading', { name: 'Mystery Writer' })).toBeInTheDocument()
    expect(screen.getAllByText('No ratings yet')).toHaveLength(2)
    expect(screen.getByText('N/A')).toBeInTheDocument()
    expect(screen.getByText(/unrated/)).toBeInTheDocument()
    expect(screen.getByText('Old Man Logan')).toBeInTheDocument()
    expect(screen.queryByText('Read, not rated')).not.toBeInTheDocument()
  })

  it('explains an empty comparison instead of rendering empty cards', () => {
    mockedHook.mockReturnValue(baseHook({ data: makeResponse() }))

    renderAt('creator:7,creator:12')

    expect(screen.getByText('Comparing 0 creators')).toBeInTheDocument()
    expect(
      screen.getByText('None of the selected creators were found in your library.'),
    ).toBeInTheDocument()
  })
})
