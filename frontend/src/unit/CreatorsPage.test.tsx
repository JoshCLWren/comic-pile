import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CreatorsPage from '../pages/CreatorsPage'
import CreatorComparisonPage from '../pages/CreatorComparisonPage'
import { useCreatorsList } from '../hooks/useCreatorsList'
import { useCreatorComparison } from '../hooks/useCreatorComparison'
import type { CreatorListSelection, CreatorsListState } from '../hooks/useCreatorsList'
import type { CreatorListItem } from '../services/api-creators'
import type { CreatorComparisonItem } from '../types/index'

vi.mock('../hooks/useCreatorsList', () => ({
  useCreatorsList: vi.fn(),
}))

vi.mock('../hooks/useCreatorComparison', () => ({
  useCreatorComparison: vi.fn(),
}))

vi.mock('../hooks/useDebounce', () => ({
  useDebounce: <T,>(value: T) => value,
}))

const mockedHook = vi.mocked(useCreatorsList)
const mockedComparisonHook = vi.mocked(useCreatorComparison)

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

function makeItem(overrides: Partial<CreatorListItem> & { canonical_creator_key: string }): CreatorListItem {
  return {
    display_name: 'A Creator',
    normalized_roles: ['writer'],
    average_rating: 4.5,
    ratings_count: 2,
    ...overrides,
  }
}

function baseState(overrides: Partial<CreatorsListState> = {}): CreatorsListState {
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

function CompareProbe() {
  const [params] = useSearchParams()
  return <div>Compare page: {params.get('keys')}</div>
}

/** Surfaces the live URL so tests can assert the durable `keys` contract. */
function LocationProbe() {
  const location = useLocation()
  return <div data-testid="location-search">{location.search}</div>
}

/** Browser-style history controls unavailable inside a MemoryRouter. */
function HistoryControls() {
  const navigate = useNavigate()
  return (
    <div>
      <button type="button" onClick={() => navigate(-1)}>
        history back
      </button>
      <button type="button" onClick={() => navigate(1)}>
        history forward
      </button>
    </div>
  )
}

function currentKeysParam(): string | null {
  const search = screen.getByTestId('location-search').textContent ?? ''
  return new URLSearchParams(search).get('keys')
}

function makeComparisonItem(key: string, displayName: string): CreatorComparisonItem {
  return {
    canonical_creator_key: key,
    display_name: displayName,
    normalized_roles: ['writer'],
    average_rating: 4.5,
    median_rating: 4.5,
    ratings_count: 4,
    rating_distribution: { '5': 4 },
    top_rating_rate: 1,
    role_stats: [],
    strongest_series: [],
    min_rated_issues_per_series: 5,
    unread_upcoming_count: 0,
    read_unrated_count: 0,
    unread_issue_refs: [],
    read_unrated_issue_refs: [],
    max_issue_refs_per_group: 5,
    insufficient_data: false,
  }
}

function renderPage(
  extraRoutes?: { path: string; element: React.ReactNode }[],
  initialEntry = '/creators',
) {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <LocationProbe />
      <HistoryControls />
      <Routes>
        <Route path="/creators" element={<CreatorsPage />} />
        {extraRoutes?.map((route) => (
          <Route key={route.path} path={route.path} element={route.element} />
        ))}
      </Routes>
    </MemoryRouter>,
  )
}

/** The two creators used by the selection round-trip tests. */
const BRIAN = makeItem({ canonical_creator_key: 'creator:7', display_name: 'Brian K. Vaughan' })
const STEVE = makeItem({ canonical_creator_key: 'creator:12', display_name: 'Steve McNiven' })
const FIONA = makeItem({ canonical_creator_key: 'creator:13', display_name: 'Fiona Staples' })

function selectionState() {
  mockedHook.mockReturnValue(
    baseState({ items: [BRIAN, STEVE, FIONA], total: 3, hasMore: false }),
  )
  mockedComparisonHook.mockImplementation((keys) => {
    const displayNames = new Map(
      [BRIAN, STEVE, FIONA].map((item) => [item.canonical_creator_key, item.display_name]),
    )
    const comparisons = Object.fromEntries(
      (keys ?? []).map((key) => [key, makeComparisonItem(key, displayNames.get(key) ?? key)]),
    )
    return {
      data: { comparisons, coverage: COMPLETE_COVERAGE, insufficient_data_keys: [] },
      isPending: false,
      isError: false,
      error: null,
    }
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  mockedHook.mockReturnValue(baseState())
  mockedComparisonHook.mockReturnValue({
    data: undefined,
    isPending: false,
    isError: false,
    error: null,
  })
})

describe('CreatorsPage', () => {
  it('renders a loading state while the first page is pending', () => {
    mockedHook.mockReturnValue(baseState({ isPending: true }))

    renderPage()

    expect(screen.getByLabelText('Loading creators')).toBeInTheDocument()
  })

  it('renders a recoverable error state that is distinct from an empty state', () => {
    const refetch = vi.fn()
    mockedHook.mockReturnValue(baseState({ isError: true, error: new Error('boom'), refetch }))

    renderPage()

    expect(screen.getByRole('alert')).toHaveTextContent('Could not load your creators')
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(refetch).toHaveBeenCalled()
  })

  it('explains an empty library instead of rendering an empty grid', () => {
    mockedHook.mockReturnValue(baseState())

    renderPage()

    expect(
      screen.getByText('No rated creators yet. Rating an issue adds its creators here.'),
    ).toBeInTheDocument()
    expect(screen.queryByRole('list')).not.toBeInTheDocument()
  })

  it('distinguishes an empty search result from an empty library', () => {
    mockedHook.mockReturnValue(baseState())

    renderPage()

    fireEvent.change(screen.getByLabelText('Search creators by name'), {
      target: { value: 'Nobody' },
    })

    expect(screen.getByText('No creators match “Nobody”.')).toBeInTheDocument()
  })

  it('renders personal name, roles, rating count, and average for every row', () => {
    mockedHook.mockReturnValue(
      baseState({
        items: [
          makeItem({
            canonical_creator_key: 'creator:7',
            display_name: 'Brian K. Vaughan',
            normalized_roles: ['writer', 'editor'],
            average_rating: 4.5,
            ratings_count: 7,
          }),
          makeItem({
            canonical_creator_key: 'creator:12',
            display_name: 'Steve McNiven',
            normalized_roles: ['artist'],
            average_rating: null,
            ratings_count: 1,
          }),
        ],
        total: 2,
      }),
    )

    renderPage()

    expect(screen.getByText('Brian K. Vaughan')).toBeInTheDocument()
    expect(screen.getByText('writer, editor')).toBeInTheDocument()
    expect(screen.getByText('7 rated issues')).toBeInTheDocument()
    expect(screen.getByText('4.5★')).toBeInTheDocument()
    expect(screen.getByText('Steve McNiven')).toBeInTheDocument()
    expect(screen.getByText('1 rated issue')).toBeInTheDocument()
    expect(screen.getByText('unrated')).toBeInTheDocument()
    expect(screen.getByText('Showing 2 of 2 creators')).toBeInTheDocument()
  })

  it('keeps two distinct canonical creators with the same display name as separate rows', () => {
    mockedHook.mockReturnValue(
      baseState({
        items: [
          makeItem({ canonical_creator_key: 'creator:7', display_name: 'Alex Kim' }),
          makeItem({ canonical_creator_key: 'creator:9', display_name: 'Alex Kim' }),
        ],
        total: 2,
      }),
    )

    renderPage()

    const links = screen.getAllByRole('link', { name: /Alex Kim/ })
    expect(links).toHaveLength(2)
    expect(links[0]).toHaveAttribute('href', '/creators/creator%3A7')
    expect(links[1]).toHaveAttribute('href', '/creators/creator%3A9')
  })

  it('links a row to the existing creator detail route for its canonical key', () => {
    mockedHook.mockReturnValue(
      baseState({
        items: [makeItem({ canonical_creator_key: 'creator:7', display_name: 'Brian K. Vaughan' })],
        total: 1,
      }),
    )

    renderPage([{ path: '/creators/:creatorKey', element: <div>Creator detail</div> }])

    const link = screen.getByRole('link', { name: /Brian K. Vaughan/ })
    expect(link).toHaveAttribute('href', '/creators/creator%3A7')

    fireEvent.click(link)
    expect(screen.getByText('Creator detail')).toBeInTheDocument()
  })

  it('never links a row whose key is not a canonical creator identity', () => {
    mockedHook.mockReturnValue(
      baseState({
        items: [makeItem({ canonical_creator_key: 'Alex Kim', display_name: 'Alex Kim' })],
        total: 1,
      }),
    )

    renderPage()

    expect(screen.queryByRole('link')).not.toBeInTheDocument()
    expect(screen.getByText('Alex Kim')).toBeInTheDocument()
  })

  it('requests the server-side ordering instead of sorting client-side', () => {
    const seen: CreatorListSelection[] = []
    mockedHook.mockImplementation((selection) => {
      seen.push(selection)
      return baseState()
    })

    renderPage()

    fireEvent.change(screen.getByLabelText('Sort'), { target: { value: 'ratings_count' } })
    fireEvent.change(screen.getByLabelText('Sort'), { target: { value: 'average_rating' } })
    fireEvent.change(screen.getByLabelText('Sort'), { target: { value: 'name' } })

    expect(seen.map((selection) => selection.sort)).toEqual([
      'name',
      'ratings_count',
      'average_rating',
      'name',
    ])
  })

  it('keeps the current ordering when the select reports an unknown value', () => {
    const seen: CreatorListSelection[] = []
    mockedHook.mockImplementation((selection) => {
      seen.push(selection)
      return baseState()
    })

    renderPage()

    fireEvent.change(screen.getByLabelText('Sort'), { target: { value: 'not_a_sort' } })

    expect(seen.map((selection) => selection.sort)).toEqual(['name'])
  })

  it('passes a trimmed name search through to the bounded discovery contract', () => {
    const seen: CreatorListSelection[] = []
    mockedHook.mockImplementation((selection) => {
      seen.push(selection)
      return baseState()
    })

    renderPage()

    fireEvent.change(screen.getByLabelText('Search creators by name'), {
      target: { value: '  vaughan  ' },
    })

    expect(seen.at(-1)).toEqual({ search: 'vaughan', sort: 'name' })
  })

  it('appends another page through load more without hiding loaded rows', async () => {
    const loadMore = vi.fn().mockResolvedValue(undefined)
    mockedHook.mockReturnValue(
      baseState({
        items: [makeItem({ canonical_creator_key: 'creator:7', display_name: 'Brian K. Vaughan' })],
        total: 40,
        hasMore: true,
        loadMore,
      }),
    )

    renderPage()

    expect(screen.getByText('Showing 1 of 40 creators')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Load more' }))
    expect(loadMore).toHaveBeenCalled()
    expect(screen.getByText('Brian K. Vaughan')).toBeInTheDocument()
  })

  it('shows a busy load-more control while the next page loads', () => {
    mockedHook.mockReturnValue(
      baseState({
        items: [makeItem({ canonical_creator_key: 'creator:7' })],
        total: 40,
        hasMore: true,
        isFetchingMore: true,
      }),
    )

    renderPage()

    const button = screen.getByRole('button', { name: 'Loading more…' })
    expect(button).toBeDisabled()
  })

  it('hides load more when the last page is reached', () => {
    mockedHook.mockReturnValue(
      baseState({
        items: [makeItem({ canonical_creator_key: 'creator:7' })],
        total: 1,
        hasMore: false,
      }),
    )

    renderPage()

    expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument()
  })

  it('keeps loaded rows and explains a failed additional page', () => {
    mockedHook.mockReturnValue(
      baseState({
        items: [makeItem({ canonical_creator_key: 'creator:7', display_name: 'Brian K. Vaughan' })],
        total: 40,
        isError: true,
        error: new Error('boom'),
        hasMore: true,
      }),
    )

    renderPage()

    expect(screen.getByText('Brian K. Vaughan')).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('Could not load more creators')
  })

  it('preserves the partial-coverage signal instead of claiming an exhaustive list', () => {
    mockedHook.mockReturnValue(
      baseState({
        coverage: { ...COMPLETE_COVERAGE, ratings_complete: false },
        items: [makeItem({ canonical_creator_key: 'creator:7' })],
        total: 1,
      }),
    )

    renderPage()

    expect(screen.getByRole('note')).toHaveTextContent(
      'Partial list: some rated issues are still missing creator metadata',
    )
  })

  it('does not show a coverage caveat when metadata coverage is complete', () => {
    mockedHook.mockReturnValue(
      baseState({ items: [makeItem({ canonical_creator_key: 'creator:7' })], total: 1 }),
    )

    renderPage()

    expect(screen.queryByRole('note')).not.toBeInTheDocument()
  })

  it('selects creators for comparison and opens the bounded compare route', () => {
    mockedHook.mockReturnValue(
      baseState({
        items: [
          makeItem({ canonical_creator_key: 'creator:7', display_name: 'Brian K. Vaughan' }),
          makeItem({ canonical_creator_key: 'creator:12', display_name: 'Steve McNiven' }),
        ],
        total: 2,
      }),
    )

    renderPage([{ path: '/creators/compare', element: <CompareProbe /> }])

    expect(screen.queryByRole('button', { name: 'Compare' })).not.toBeInTheDocument()

    fireEvent.click(screen.getByLabelText('Select Brian K. Vaughan for comparison'))
    expect(screen.getByText('1 of 4 selected for comparison')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Compare' })).not.toBeInTheDocument()

    fireEvent.click(screen.getByLabelText('Select Steve McNiven for comparison'))
    expect(screen.getByText('2 of 4 selected for comparison')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Compare' }))
    expect(screen.getByText(/Compare page/)).toHaveTextContent('creator:7,creator:12')
  })

  it('clears the comparison selection without losing loaded rows', () => {
    mockedHook.mockReturnValue(
      baseState({
        items: [
          makeItem({ canonical_creator_key: 'creator:7', display_name: 'Brian K. Vaughan' }),
          makeItem({ canonical_creator_key: 'creator:12', display_name: 'Steve McNiven' }),
        ],
        total: 2,
      }),
    )

    renderPage()

    fireEvent.click(screen.getByLabelText('Select Brian K. Vaughan for comparison'))
    fireEvent.click(screen.getByLabelText('Select Steve McNiven for comparison'))
    expect(screen.getByText('2 of 4 selected for comparison')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Clear selection' }))

    expect(screen.queryByText(/selected for comparison/)).not.toBeInTheDocument()
    expect(screen.getByText('Brian K. Vaughan')).toBeInTheDocument()
    expect(screen.getByText('Steve McNiven')).toBeInTheDocument()
  })

  it('caps comparison selection at four creators', () => {
    mockedHook.mockReturnValue(
      baseState({
        items: [1, 2, 3, 4, 5].map((id) =>
          makeItem({ canonical_creator_key: `creator:${id}`, display_name: `Creator ${id}` }),
        ),
        total: 5,
      }),
    )

    renderPage()

    for (const id of [1, 2, 3, 4]) {
      fireEvent.click(screen.getByLabelText(`Select Creator ${id} for comparison`))
    }

    expect(screen.getByText('4 of 4 selected for comparison')).toBeInTheDocument()
    expect(screen.getByLabelText('Select Creator 5 for comparison')).toBeDisabled()

    fireEvent.click(screen.getByLabelText('Select Creator 1 for comparison'))

    expect(screen.getByText('3 of 4 selected for comparison')).toBeInTheDocument()
    expect(screen.getByLabelText('Select Creator 5 for comparison')).not.toBeDisabled()
  })
})

describe('CreatorsPage minimum-rated-sample control', () => {
  it('passes the selected minimum sample through to the bounded contract', () => {
    const seen: CreatorListSelection[] = []
    mockedHook.mockImplementation((selection) => {
      seen.push(selection)
      return baseState()
    })

    renderPage()

    fireEvent.change(screen.getByLabelText('Minimum rated'), { target: { value: '5' } })
    fireEvent.change(screen.getByLabelText('Minimum rated'), { target: { value: '0' } })

    expect(seen.map((selection) => selection.minRatings)).toEqual([undefined, 5, undefined])
  })

  it('offers the bounded choices Any/3+/5+/10+/25+', () => {
    renderPage()

    // SAFETY: getByLabelText('Minimum rated') returns the select rendered by CreatorsPage for the minimum-sample control, so the element is an HTMLSelectElement.
    const select = screen.getByLabelText('Minimum rated') as HTMLSelectElement
    expect([...select.options].map((option) => option.textContent)).toEqual([
      'Any',
      '3+',
      '5+',
      '10+',
      '25+',
    ])
  })

  it('flags a high average backed by a tiny sample', () => {
    mockedHook.mockReturnValue(
      baseState({
        items: [
          makeItem({ canonical_creator_key: 'creator:1', average_rating: 5.0, ratings_count: 2 }),
          makeItem({ canonical_creator_key: 'creator:2', average_rating: 5.0, ratings_count: 12 }),
        ],
        total: 2,
      }),
    )

    renderPage()

    expect(screen.getByText('small sample')).toBeTruthy()
  })
})

describe('CreatorsPage small-sample explanation (#3627)', () => {
  function sampleRow(ratingsCount = 2, averageRating: number | null = 5.0) {
    mockedHook.mockReturnValue(
      baseState({
        items: [
          makeItem({
            canonical_creator_key: 'creator:1',
            average_rating: averageRating,
            ratings_count: ratingsCount,
          }),
        ],
        total: 1,
      }),
    )
    renderPage()
  }

  function sampleBadge(): HTMLElement | null {
    return screen.queryByRole('button', { name: /Small sample/ })
  }

  it('keeps the explanation collapsed until the reader activates it', () => {
    sampleRow()

    const badge = screen.getByRole('button', { name: /Small sample/ })
    const panel = document.getElementById(badge.getAttribute('aria-controls') ?? '')
    expect(panel).not.toBeNull()
    expect(panel).not.toBeVisible()
    expect(badge.getAttribute('aria-expanded')).toBe('false')

    fireEvent.click(badge)

    expect(badge.getAttribute('aria-expanded')).toBe('true')
    expect(panel).toBeVisible()
    expect(panel).toHaveTextContent(/may be less representative/)
    expect(panel).toHaveTextContent(/confidence\/context indicator/)
  })

  it('keeps the small-sample control outside the creator row link', () => {
    sampleRow()

    const badge = screen.getByRole('button', { name: /Small sample/ })
    expect(badge.closest('a')).toBeNull()
  })

  it('exposes a theme focus ring and wraps the expanded explanation', () => {
    sampleRow()

    const badge = screen.getByRole('button', { name: /Small sample/ })
    expect(badge.className).toContain('focus-visible:ring-2')
    expect(badge.className).toContain('focus-visible:ring-[var(--theme-focus-ring)]')

    fireEvent.click(badge)

    const panel = document.getElementById(badge.getAttribute('aria-controls') ?? '')
    expect(panel).not.toBeNull()
    expect(panel?.className).toContain('basis-full')
    expect(panel?.className).toContain('break-words')
    expect(panel?.parentElement?.className).toContain('flex-wrap')
  })

  it('links the explanation to the canonical glossary anchor', () => {
    sampleRow()

    fireEvent.click(screen.getByRole('button', { name: /Small sample/ }))

    expect(screen.getByRole('link', { name: 'Glossary' })).toHaveAttribute(
      'href',
      '/glossary#small-sample',
    )
  })

  it('closes on Escape from inside the explanation and returns focus to the control', () => {
    sampleRow()

    const badge = screen.getByRole('button', { name: /Small sample/ })
    fireEvent.click(badge)

    const glossaryLink = screen.getByRole('link', { name: 'Glossary' })
    glossaryLink.focus()
    fireEvent.keyDown(glossaryLink, { key: 'Escape' })

    expect(badge.getAttribute('aria-expanded')).toBe('false')
    expect(document.getElementById(badge.getAttribute('aria-controls') ?? '')).not.toBeVisible()
    expect(document.activeElement).toBe(badge)
  })

  // Guards the authoritative production threshold (#3627 asked for "three";
  // the shipped creator metric has always used five, and the issue forbids
  // changing it). Counts are headline-rated distinct comics.
  it.each([1, 2, 4])('flags a creator with %i rated comics', (count) => {
    sampleRow(count)

    const badge = screen.getByRole('button', { name: /Small sample/ })
    const panel = document.getElementById(badge.getAttribute('aria-controls') ?? '')
    expect(panel).not.toBeVisible()

    fireEvent.click(badge)

    expect(panel).toBeVisible()
  })

  it.each([5, 6])('does not flag a creator with %i rated comics', (count) => {
    sampleRow(count)

    expect(sampleBadge()).toBeNull()
  })

  it('does not flag an unrated creator that has no average yet', () => {
    sampleRow(0, null)

    expect(sampleBadge()).toBeNull()
    expect(screen.getByText('unrated')).toBeInTheDocument()
  })
})

describe('CreatorsPage comparison selection URL contract', () => {
  it('restores checked creators from a keyed URL and keeps each one uncheckable', () => {
    selectionState()

    renderPage(undefined, '/creators?keys=creator:7,creator:12')

    const brian = screen.getByLabelText('Select Brian K. Vaughan for comparison')
    const steve = screen.getByLabelText('Select Steve McNiven for comparison')
    expect(brian).toBeChecked()
    expect(steve).toBeChecked()
    expect(brian).not.toBeDisabled()
    expect(steve).not.toBeDisabled()
    expect(screen.getByLabelText('Select Fiona Staples for comparison')).not.toBeChecked()
    expect(screen.getByText('2 of 4 selected for comparison')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Compare' })).toBeInTheDocument()
  })

  it('drops malformed keys and collapses duplicate keys instead of trusting the URL', () => {
    selectionState()

    renderPage(
      undefined,
      '/creators?keys=creator:7,creator:7,bogus,creator:invalid,creator:12,9',
    )

    expect(screen.getByText('2 of 4 selected for comparison')).toBeInTheDocument()
    expect(screen.getByLabelText('Select Brian K. Vaughan for comparison')).toBeChecked()
    expect(screen.getByLabelText('Select Steve McNiven for comparison')).toBeChecked()
    expect(screen.getByLabelText('Select Fiona Staples for comparison')).not.toBeChecked()
  })

  it('caps a restored selection at the four-creator maximum', () => {
    mockedHook.mockReturnValue(
      baseState({
        items: [1, 2, 3, 4, 5].map((id) =>
          makeItem({ canonical_creator_key: `creator:${id}`, display_name: `Creator ${id}` }),
        ),
        total: 5,
      }),
    )

    renderPage(
      undefined,
      '/creators?keys=creator:1,creator:2,creator:3,creator:4,creator:5',
    )

    expect(screen.getByText('4 of 4 selected for comparison')).toBeInTheDocument()
    for (const id of [1, 2, 3, 4]) {
      expect(screen.getByLabelText(`Select Creator ${id} for comparison`)).toBeChecked()
    }
    expect(screen.getByLabelText('Select Creator 5 for comparison')).not.toBeChecked()
  })

  it('writes additions and removals back to the URL deterministically', () => {
    selectionState()

    renderPage(undefined, '/creators?keys=creator:7')
    expect(currentKeysParam()).toBe('creator:7')

    fireEvent.click(screen.getByLabelText('Select Steve McNiven for comparison'))
    expect(currentKeysParam()).toBe('creator:7,creator:12')

    fireEvent.click(screen.getByLabelText('Select Brian K. Vaughan for comparison'))
    expect(currentKeysParam()).toBe('creator:12')
    expect(screen.getByText('1 of 4 selected for comparison')).toBeInTheDocument()
  })

  it('preserves unrelated URL parameters when writing the selection', () => {
    selectionState()

    renderPage(undefined, '/creators?keys=creator:7&theme=ink-gold')

    fireEvent.click(screen.getByLabelText('Select Steve McNiven for comparison'))

    const search = new URLSearchParams(screen.getByTestId('location-search').textContent ?? '')
    expect(search.get('keys')).toBe('creator:7,creator:12')
    expect(search.get('theme')).toBe('ink-gold')
  })

  it('clears the keys parameter when the reader clears the selection', () => {
    selectionState()

    renderPage(undefined, '/creators?keys=creator:7,creator:12')

    fireEvent.click(screen.getByRole('button', { name: 'Clear selection' }))

    expect(currentKeysParam()).toBeNull()
    expect(screen.queryByText(/selected for comparison/)).not.toBeInTheDocument()
    expect(screen.getByLabelText('Select Brian K. Vaughan for comparison')).not.toBeChecked()
  })

  it('keeps restored creators selected through a browser Back/forward round trip to compare', () => {
    selectionState()

    renderPage(
      [{ path: '/creators/compare', element: <CompareProbe /> }],
      '/creators?keys=creator:7,creator:12',
    )

    fireEvent.click(screen.getByRole('button', { name: 'Compare' }))
    expect(screen.getByText(/Compare page/)).toHaveTextContent('creator:7,creator:12')

    fireEvent.click(screen.getByRole('button', { name: 'history back' }))
    expect(screen.getByLabelText('Select Brian K. Vaughan for comparison')).toBeChecked()
    expect(screen.getByLabelText('Select Steve McNiven for comparison')).toBeChecked()
    expect(screen.getByText('2 of 4 selected for comparison')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'history forward' }))
    expect(screen.getByText(/Compare page/)).toHaveTextContent('creator:7,creator:12')
  })

  it('replaces one selected creator with another and re-compares with the exact new set', () => {
    selectionState()

    renderPage(
      [{ path: '/creators/compare', element: <CompareProbe /> }],
      '/creators?keys=creator:7,creator:12',
    )

    fireEvent.click(screen.getByLabelText('Select Brian K. Vaughan for comparison'))
    expect(screen.getByText('1 of 4 selected for comparison')).toBeInTheDocument()
    expect(currentKeysParam()).toBe('creator:12')
    expect(screen.queryByRole('button', { name: 'Compare' })).not.toBeInTheDocument()

    fireEvent.click(screen.getByLabelText('Select Fiona Staples for comparison'))
    expect(screen.getByText('2 of 4 selected for comparison')).toBeInTheDocument()
    expect(currentKeysParam()).toBe('creator:12,creator:13')

    fireEvent.click(screen.getByRole('button', { name: 'Compare' }))
    expect(screen.getByText(/Compare page/)).toHaveTextContent('creator:12,creator:13')
  })

  it('returns from the comparison screen through Change selection with the same creators selected', () => {
    selectionState()

    renderPage(
      [{ path: '/creators/compare', element: <CreatorComparisonPage /> }],
      '/creators?keys=creator:7,creator:12',
    )

    fireEvent.click(screen.getByRole('button', { name: 'Compare' }))
    expect(screen.getByRole('heading', { name: 'Creator Comparison' })).toBeInTheDocument()
    expect(screen.getByText('Comparing 2 creators')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('link', { name: 'Change selection' }))

    expect(currentKeysParam()).toBe('creator:7,creator:12')
    expect(screen.getByLabelText('Select Brian K. Vaughan for comparison')).toBeChecked()
    expect(screen.getByLabelText('Select Steve McNiven for comparison')).toBeChecked()
    expect(screen.getByRole('button', { name: 'Compare' })).toBeInTheDocument()
  })

  it('does not let an unknown key consume a selection slot or crowd out a valid one', () => {
    selectionState()

    renderPage(undefined, '/creators?keys=creator:9999,creator:7,creator:12')

    expect(screen.getByText('2 of 4 selected for comparison')).toBeInTheDocument()
    expect(screen.getByLabelText('Select Brian K. Vaughan for comparison')).toBeChecked()
    expect(screen.getByLabelText('Select Steve McNiven for comparison')).toBeChecked()
    expect(screen.getByLabelText('Select Fiona Staples for comparison')).not.toBeChecked()
    // The unknown key is preserved in the URL (this page can't confirm it isn't a
    // real creator elsewhere in the list) but never occupies a selection slot.
    expect(currentKeysParam()).toBe('creator:9999,creator:7,creator:12')
  })

  it('preserves a valid selection for a creator not on the current page', () => {
    mockedHook.mockReturnValue(
      baseState({ items: [BRIAN], total: 2, hasMore: true }),
    )

    renderPage(undefined, '/creators?keys=creator:7,creator:13')

    expect(screen.getByLabelText('Select Brian K. Vaughan for comparison')).toBeChecked()
    expect(screen.getByText('1 of 4 selected for comparison')).toBeInTheDocument()
    // A valid key for a creator not yet loaded must not be deleted from the URL,
    // so the selection survives list changes and can be checked once loaded (#4208).
    expect(currentKeysParam()).toBe('creator:7,creator:13')
  })

  it('deduplicates duplicate keys in the URL without inflating the counter', () => {
    selectionState()

    renderPage(undefined, '/creators?keys=creator:7,creator:7,creator:12,creator:12')

    expect(screen.getByText('2 of 4 selected for comparison')).toBeInTheDocument()
    expect(screen.getByLabelText('Select Brian K. Vaughan for comparison')).toBeChecked()
    expect(screen.getByLabelText('Select Steve McNiven for comparison')).toBeChecked()
    expect(screen.getByLabelText('Select Fiona Staples for comparison')).not.toBeChecked()
  })

  it('canonicalizes a duplicated selection URL instead of leaving repeated keys in place', async () => {
    selectionState()

    renderPage(undefined, '/creators?keys=creator:7,creator:7,creator:12,creator:12')

    // The repeat collapses in the durable URL too, so Change selection,
    // Compare, and a reload all carry the same two identities (#4208).
    await waitFor(() => expect(currentKeysParam()).toBe('creator:7,creator:12'))
  })

  it('keeps an off-page selection when a visible checkbox is toggled', () => {
    mockedHook.mockReturnValue(baseState({ items: [BRIAN, STEVE], total: 3, hasMore: true }))

    renderPage(undefined, '/creators?keys=creator:7,creator:13')

    expect(screen.getByText('1 of 4 selected for comparison')).toBeInTheDocument()

    fireEvent.click(screen.getByLabelText('Select Brian K. Vaughan for comparison'))

    // creator:13 is on a page that is not loaded yet; toggling a visible row
    // must not delete it, otherwise the selection is unrecoverable (#4208).
    expect(currentKeysParam()).toBe('creator:13')
    expect(screen.queryByText(/selected for comparison/)).not.toBeInTheDocument()
  })

  it('drops malformed keys from the URL while preserving valid selections', async () => {
    selectionState()

    renderPage(undefined, '/creators?keys=creator:7,bogus,creator:12,creator:invalid')

    expect(screen.getByText('2 of 4 selected for comparison')).toBeInTheDocument()
    await waitFor(() => expect(currentKeysParam()).toBe('creator:7,creator:12'))
  })
})
