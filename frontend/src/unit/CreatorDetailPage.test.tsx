import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CreatorDetailPage from '../pages/CreatorDetailPage'
import { useCreatorDetail } from '../hooks/useCreatorDetail'
import type { CreatorDetailState } from '../hooks/useCreatorDetail'
import { useCreatorSeriesIssues } from '../hooks/useCreatorSeriesIssues'
import type { CreatorIssueInsight } from '../services/api-creators'

vi.mock('../hooks/useCreatorDetail', () => ({
  useCreatorDetail: vi.fn(),
}))

vi.mock('../hooks/useCreatorSeriesIssues', () => ({
  useCreatorSeriesIssues: vi.fn(),
}))

const mockedHook = vi.mocked(useCreatorDetail)
const mockedSeriesIssues = vi.mocked(useCreatorSeriesIssues)

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
      { role: 'writer', issue_count: 5, rated_issue_count: 3, average_rating: 4.5 },
      { role: 'cover', issue_count: 1, rated_issue_count: 0, average_rating: null },
    ],
    ratingDistribution: null,
    insights: null,
    seriesGroups: [
      {
        series_key: 'thread:1',
        thread_id: 1,
        thread_title: 'Series A',
        rated_issue_count: 2,
        average_rating: 4.5,
        lowest_rating: 4,
        highest_rating: 5,
        roles: ['writer'],
        unread_issue_count: 0,
        read_unrated_issue_count: 0,
        metadata_complete: true,
        sort_key: '0002:Series A:thread:1',
        population_scope: 'all_verified_credits',
      },
    ],
    seriesGroupsTotal: 1,
    seriesGroupsComplete: true,
    headlineRoles: ['artist', 'colorist', 'inker', 'letterer', 'penciler', 'writer'],
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
  mockedSeriesIssues.mockReturnValue({
    data: undefined,
    isPending: false,
    isError: false,
  } as unknown as ReturnType<typeof useCreatorSeriesIssues>)
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
    const ratedLink = screen.getByRole('link', { name: /Series A #1/ })
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

  it('renders series groups from the API with grouped aggregates', () => {
    renderAt('creator:7')

    expect(screen.getByRole('heading', { name: 'Series (1)' })).toBeInTheDocument()
    const seriesLink = screen.getByRole('link', { name: /Series A.*2 issues/ })
    expect(seriesLink.getAttribute('href')).toBe('/thread/1')
    expect(screen.getByLabelText('Average 4.5 out of 5')).toBeInTheDocument()
  })

  it('hides the series section when the backend reports no groups', () => {
    mockedHook.mockReturnValue(baseState({ seriesGroups: [], seriesGroupsTotal: 0 }))
    renderAt('creator:7')

    expect(screen.queryByRole('heading', { name: /Series/ })).not.toBeInTheDocument()
  })

  it('communicates partial series groups as lower-bound results', () => {
    mockedHook.mockReturnValue(baseState({ seriesGroupsComplete: false }))
    renderAt('creator:7')

    expect(screen.getByText(/Partial list: showing the most-rated series first/)).toBeInTheDocument()
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
    expect(screen.getByRole('link', { name: /Series A #1/ })).toBeInTheDocument()
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

describe('CreatorDetailPage rating distribution', () => {
  const distribution = {
    buckets: [
      { rating: 0.5, count: 0 },
      { rating: 1.0, count: 0 },
      { rating: 1.5, count: 0 },
      { rating: 2.0, count: 0 },
      { rating: 2.5, count: 1 },
      { rating: 3.0, count: 0 },
      { rating: 3.5, count: 0 },
      { rating: 4.0, count: 0 },
      { rating: 4.5, count: 1 },
      { rating: 5.0, count: 0 },
    ],
    sample_count: 2,
    mean_rating: 3.5,
    median_rating: 3.5,
    min_rating: 2.5,
    max_rating: 4.5,
  }

  it('renders median, range, average, and sample strength', () => {
    mockedHook.mockReturnValue(baseState({ ratingDistribution: distribution }))

    renderAt('creator:7')

    expect(screen.getByRole('heading', { name: 'Rating distribution' })).toBeTruthy()
    expect(screen.getByText('Median').parentElement?.textContent).toContain('3.5★')
    expect(screen.getByText('Range').parentElement?.textContent).toContain('2.5★–4.5★')
    expect(screen.getByText('Average').parentElement?.textContent).toContain('3.50★')
    expect(screen.getByText('Sample').parentElement?.textContent).toContain('2 issues')
  })

  it('renders an accessible per-bucket histogram', () => {
    mockedHook.mockReturnValue(baseState({ ratingDistribution: distribution }))

    renderAt('creator:7')

    expect(screen.getByLabelText('1 rating at 2.5 stars')).toBeTruthy()
    expect(screen.getByLabelText('1 rating at 4.5 stars')).toBeTruthy()
    expect(screen.getByLabelText('0 ratings at 1.0 stars')).toBeTruthy()
  })

  it('marks a partial distribution as a lower bound, not exhaustive', () => {
    mockedHook.mockReturnValue(
      baseState({
        ratingDistribution: distribution,
        coverage: {
          ...baseState().coverage!,
          rated_issues_total: 5,
          rated_issues_with_creator_metadata: 2,
          ratings_complete: false,
        },
      }),
    )

    renderAt('creator:7')

    expect(screen.getAllByRole('note').map((n) => n.textContent).join(' ')).toContain('Distribution reflects only')
  })
})

describe('CreatorDetailPage highlights (#3092)', () => {
  const insights = {
    min_series_sample: 3,
    series_sample_met: true,
    series_message: null,
    excluded_incomplete_series_count: 0,
    individual_issue_limit: 3,
    individual_issues_combined: false,
    strongest_series: {
      series_key: 'thread:9',
      thread_id: 9,
      thread_title: 'Best Run',
      rated_issue_count: 4,
      average_rating: 4.8,
      lowest_rating: 4,
      highest_rating: 5,
      roles: ['writer'],
      metadata_complete: true,
      sort_key: 'thread:9',
    },
    weakest_series: {
      series_key: 'thread:11',
      thread_id: 11,
      thread_title: 'Weak Run',
      rated_issue_count: 3,
      average_rating: 2.5,
      lowest_rating: 1.5,
      highest_rating: 3.5,
      roles: ['artist'],
      metadata_complete: true,
      sort_key: 'thread:11',
    },
    most_rated_series: {
      series_key: 'thread:12',
      thread_id: 12,
      thread_title: 'Long Run',
      rated_issue_count: 7,
      average_rating: 4,
      lowest_rating: 3,
      highest_rating: 5,
      roles: ['writer'],
      metadata_complete: true,
      sort_key: 'thread:12',
    },
    highest_rated_issues: [
      {
        issue_id: 91,
        issue_number: '7',
        thread_id: 9,
        thread_title: 'Best Run',
        effective_rating: 5,
        roles: ['writer'],
        sort_key: '91',
      },
    ],
    lowest_rated_issues: [
      {
        issue_id: 92,
        issue_number: '2',
        thread_id: 11,
        thread_title: 'Weak Run',
        effective_rating: 1.5,
        roles: ['artist'],
        sort_key: '92',
      },
    ],
  }

  it('renders strongest, weakest, and most-rated series with drill-down links', () => {
    mockedHook.mockReturnValue(baseState({ insights }))
    renderAt('creator:7')

    expect(screen.getByRole('heading', { name: 'Highlights' })).toBeInTheDocument()
    expect(screen.getByText('Strongest series')).toBeInTheDocument()
    expect(screen.getByText('Weakest series')).toBeInTheDocument()
    expect(screen.getByText('Most rated series')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Strongest series.*Best Run/ })).toHaveAttribute(
      'href',
      '/thread/9',
    )
    expect(screen.getByRole('link', { name: /Weakest series.*Weak Run/ })).toHaveAttribute(
      'href',
      '/thread/11',
    )
    expect(screen.getByRole('link', { name: /Most rated series.*Long Run/ })).toHaveAttribute(
      'href',
      '/thread/12',
    )
  })

  it('separates individual issue extremes from aggregate series conclusions', () => {
    mockedHook.mockReturnValue(baseState({ insights }))
    renderAt('creator:7')

    expect(screen.getByRole('heading', { name: 'Individual issues' })).toBeInTheDocument()
    expect(
      screen.getByText('Single ratings only, not an overall best or worst verdict on the creator.'),
    ).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Highest-rated issues' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Lowest-rated issues' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Best Run #7/ })).toHaveAttribute('href', '/thread/9?issue=91#issue-91')
    expect(screen.getByRole('link', { name: /Weak Run #2/ })).toHaveAttribute('href', '/thread/11?issue=92#issue-92')
  })

  it('explains a thin series sample instead of ranking series', () => {
    mockedHook.mockReturnValue(
      baseState({
        insights: {
          ...insights,
          series_sample_met: false,
          series_message: 'Not enough rated issues in a single series yet.',
          strongest_series: null,
          weakest_series: null,
          most_rated_series: null,
        },
      }),
    )
    renderAt('creator:7')

    expect(screen.getByText('Not enough rated issues in a single series yet.')).toBeInTheDocument()
    expect(screen.queryByText('Strongest series')).not.toBeInTheDocument()
    // Individual issue extremes still surface even when series cannot be ranked.
    expect(screen.getByRole('heading', { name: 'Highest-rated issues' })).toBeInTheDocument()
  })

  it('flags series excluded for incomplete metadata as lower bounds', () => {
    mockedHook.mockReturnValue(
      baseState({ insights: { ...insights, excluded_incomplete_series_count: 2 } }),
    )
    renderAt('creator:7')

    expect(screen.getByRole('note')).toHaveTextContent(
      '2 series with rated work are not compared because creator metadata is still incomplete',
    )
  })

  it('omits the highlights section when the backend sends no insights', () => {
    mockedHook.mockReturnValue(baseState({ insights: null }))
    renderAt('creator:7')

    expect(screen.queryByRole('heading', { name: 'Highlights' })).not.toBeInTheDocument()
  })
})

describe('CreatorDetailPage highlights reasons and issue lists (#3946)', () => {
  const baseInsights = {
    min_series_sample: 3,
    series_sample_met: false,
    series_message: null,
    excluded_incomplete_series_count: 0,
    individual_issue_limit: 3,
    individual_issues_combined: false,
    strongest_series: null,
    weakest_series: null,
    most_rated_series: null,
    // SAFETY: empty array is a valid CreatorIssueInsight[]
    highest_rated_issues: [] as CreatorIssueInsight[],
    // SAFETY: empty array is a valid CreatorIssueInsight[]
    lowest_rated_issues: [] as CreatorIssueInsight[],
  }

  const issueInsight = (
    issueId: number,
    issueNumber: string,
    threadTitle: string,
    rating: number,
  ): CreatorIssueInsight => ({
    issue_id: issueId,
    issue_number: issueNumber,
    thread_id: 9,
    thread_title: threadTitle,
    effective_rating: rating,
    roles: ['writer'],
    sort_key: String(issueId),
  })

  it('names incomplete metadata when a series with enough ratings is held back', () => {
    mockedHook.mockReturnValue(
      baseState({
        insights: {
          ...baseInsights,
          series_message:
            'Series with enough rated issues are not compared yet because creator metadata is still incomplete.',
          excluded_incomplete_series_count: 1,
        },
      }),
    )
    renderAt('creator:7')

    expect(
      screen.getByText(
        'Series with enough rated issues are not compared yet because creator metadata is still incomplete.',
      ),
    ).toBeInTheDocument()
    // The thin-sample copy would contradict the three rated issues the page
    // shows for that series.
    expect(screen.queryByText(/Not enough rated issues/)).not.toBeInTheDocument()
    expect(screen.getByRole('note')).toHaveTextContent(
      '1 series with rated work is not compared because creator metadata is still incomplete',
    )
  })

  it('names the thin sample only when no series has enough rated issues', () => {
    mockedHook.mockReturnValue(
      baseState({
        insights: {
          ...baseInsights,
          series_message:
            'Not enough rated issues in a single series yet. A series needs at least 3 rated issues before it is compared as strongest or weakest.',
        },
      }),
    )
    renderAt('creator:7')

    expect(
      screen.getByText(
        'Not enough rated issues in a single series yet. A series needs at least 3 rated issues before it is compared as strongest or weakest.',
      ),
    ).toBeInTheDocument()
    expect(
      screen.queryByText(/not compared yet because creator metadata is still incomplete/),
    ).not.toBeInTheDocument()
  })

  it('never lists the same issue as both the highest and the lowest', () => {
    mockedHook.mockReturnValue(
      baseState({
        insights: {
          ...baseInsights,
          highest_rated_issues: [issueInsight(91, '7', 'Best Run', 5)],
          // A repeated issue would show the same comic as the best and the
          // worst work of the creator.
          lowest_rated_issues: [issueInsight(91, '7', 'Best Run', 5), issueInsight(92, '2', 'Weak Run', 1.5)],
        },
      }),
    )
    renderAt('creator:7')

    expect(screen.getAllByRole('link', { name: /Best Run #7/ })).toHaveLength(1)
    expect(screen.getAllByRole('link', { name: /Weak Run #2/ })).toHaveLength(1)
    expect(screen.getByRole('heading', { name: 'Highest-rated issues' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Lowest-rated issues' })).toBeInTheDocument()
  })

  it('lists a small rated set once instead of repeating it', () => {
    mockedHook.mockReturnValue(
      baseState({
        insights: {
          ...baseInsights,
          individual_issues_combined: true,
          highest_rated_issues: [
            issueInsight(91, '10', 'Promethea', 4),
            issueInsight(92, '11', 'Promethea', 3.5),
            issueInsight(93, '12', 'Promethea', 3),
          ],
          lowest_rated_issues: [],
        },
      }),
    )
    renderAt('creator:7')

    expect(screen.getByRole('heading', { name: 'Rated issues' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Highest-rated issues' })).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Lowest-rated issues' })).not.toBeInTheDocument()
    expect(screen.getAllByRole('link', { name: /Promethea #10/ })).toHaveLength(1)
    expect(screen.getAllByRole('link', { name: /Promethea #11/ })).toHaveLength(1)
    expect(screen.getAllByRole('link', { name: /Promethea #12/ })).toHaveLength(1)
    expect(
      screen.getByText(/Only 3 rated issues, so there is no separate highest and lowest/),
    ).toBeInTheDocument()
  })
})

describe('CreatorDetailPage population scopes (#3579)', () => {
  it('labels the headline Rated list and all-credits series groups explicitly', () => {
    renderAt('creator:7')

    expect(
      screen.getByText(
        'Headline roles only: artist, colorist, inker, letterer, penciler, writer. Each issue counts once in this list and the rating distribution, so a non-headline credit can appear in a series group without appearing here.',
      ),
    ).toBeInTheDocument()
    expect(screen.getByText('Rated (headline roles)')).toBeInTheDocument()
    expect(
      screen.getByText(
        'All verified credits, including roles outside the headline set. Series counts and averages can exceed the headline-only Rated list.',
      ),
    ).toBeInTheDocument()
    expect(screen.getAllByText('All verified credits').length).toBeGreaterThanOrEqual(1)
  })

  it('loads the exact issues behind a series average on demand', async () => {
    mockedSeriesIssues.mockReturnValue({
      data: {
        series_key: 'thread:1',
        thread_id: 1,
        thread_title: 'Series A',
        roles: ['cover', 'writer'],
        rated_issue_count: 2,
        average_rating: 4.5,
        lowest_rating: 4,
        highest_rating: 5,
        metadata_complete: true,
        population_scope: 'all_verified_credits',
        issues: [
          {
            issue_id: 12,
            issue_number: '2',
            thread_id: 1,
            thread_title: 'Series A',
            status: 'read',
            roles: ['cover'],
            effective_rating: 4,
            rating_timestamp: null,
            sort_key: '12',
          },
        ],
        total: 2,
        limit: 50,
        offset: 0,
        next_cursor: null,
      },
      isPending: false,
      isError: false,
    } as unknown as ReturnType<typeof useCreatorSeriesIssues>)
    renderAt('creator:7')

    expect(mockedSeriesIssues).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Show 2 issues behind this average' }))

    expect(mockedSeriesIssues).toHaveBeenCalledWith('creator:7', 'thread:1')
    expect(
      screen.getByText(
        'All verified credits. 2 rated issues back this average; each issue counts once even when several roles are credited.',
      ),
    ).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Series A #2/ })).toHaveAttribute('href', '/thread/1')
    expect(screen.getByLabelText('Rated 4 out of 5')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Hide issues behind this average' })).toHaveAttribute(
      'aria-expanded',
      'true',
    )
  })

  it('reports a drill-down failure instead of hiding the aggregate', () => {
    mockedSeriesIssues.mockReturnValue({
      data: undefined,
      isPending: false,
      isError: true,
    } as unknown as ReturnType<typeof useCreatorSeriesIssues>)
    renderAt('creator:7')

    fireEvent.click(screen.getByRole('button', { name: 'Show 2 issues behind this average' }))

    expect(screen.getByRole('alert')).toHaveTextContent(
      'Could not load the issues behind this average.',
    )
  })
})
