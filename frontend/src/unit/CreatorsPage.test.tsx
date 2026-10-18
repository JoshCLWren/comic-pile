import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useSearchParams } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CreatorsPage from '../pages/CreatorsPage'
import { useCreatorsList } from '../hooks/useCreatorsList'
import type { CreatorListSelection, CreatorsListState } from '../hooks/useCreatorsList'
import { useDiscovery, useDiscoveryModes } from '../hooks/useCreatorDiscovery'
import type { CreatorListItem, DiscoveryResultItem, DiscoveryResponse } from '../services/api-creators'

vi.mock('../hooks/useCreatorsList', () => ({
  useCreatorsList: vi.fn(),
}))

vi.mock('../hooks/useDebounce', () => ({
  useDebounce: <T,>(value: T) => value,
}))

vi.mock('../hooks/useCreatorDiscovery', () => ({
  useDiscoveryModes: vi.fn(),
  useDiscovery: vi.fn(),
}))

const mockedHook = vi.mocked(useCreatorsList)
const mockedModes = vi.mocked(useDiscoveryModes)
const mockedDiscovery = vi.mocked(useDiscovery)

/** Build a controlled `useDiscoveryModes` result; only `isLoading` drives the page. */
function modesState(
  overrides: Omit<Partial<ReturnType<typeof useDiscoveryModes>>, 'isLoading'> & {
    isLoading?: boolean
  } = {},
) {
  return { isLoading: false, ...overrides } as unknown as ReturnType<typeof useDiscoveryModes>
}

/** Build a controlled `useDiscovery` result for the discovery-mode render paths. */
function discoveryState(
  overrides: Omit<Partial<ReturnType<typeof useDiscovery>>, 'isPending'> & {
    isPending?: boolean
  } = {},
) {
  return {
    data: undefined,
    isPending: false,
    isError: false,
    refetch: vi.fn(),
    ...overrides,
  } as unknown as ReturnType<typeof useDiscovery>
}

function makeDiscovery(overrides: Partial<DiscoveryResponse> = {}): DiscoveryResponse {
  return {
    mode: 'consistently_loved',
    title: 'Most Consistently Loved',
    description: 'High average with consistent ratings',
    items: [],
    total: 0,
    limit: 20,
    offset: 0,
    ...overrides,
  }
}

function makeDiscoveryItem(
  overrides: Partial<DiscoveryResultItem> & { canonical_creator_key: string },
): DiscoveryResultItem {
  return {
    display_name: 'A Creator',
    normalized_roles: ['writer'],
    average_rating: 4.5,
    ratings_count: 2,
    qualifying_metrics: {},
    read_unrated_count: 0,
    upcoming_count: 0,
    ...overrides,
  }
}

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

function renderPage(extraRoutes?: { path: string; element: React.ReactNode }[]) {
  return render(
    <MemoryRouter initialEntries={['/creators']}>
      <Routes>
        <Route path="/creators" element={<CreatorsPage />} />
        {extraRoutes?.map((route) => (
          <Route key={route.path} path={route.path} element={route.element} />
        ))}
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  mockedHook.mockReturnValue(baseState())
  mockedModes.mockReturnValue(modesState())
  mockedDiscovery.mockReturnValue(discoveryState())
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

describe('CreatorsPage discovery insights (issue #3093)', () => {
  it('lists every curated discovery mode once the mode list is ready', () => {
    renderPage()

    for (const title of [
      'Most Consistently Loved',
      'Most Polarizing',
      'Most Read',
      'Highest Top Rating Rate',
      'Great Average, Small Sample',
      'Loved with Unread',
    ]) {
      expect(screen.getByRole('button', { name: title })).toBeInTheDocument()
    }
    expect(screen.queryByText('Loading insights...')).not.toBeInTheDocument()
  })

  it('shows a loading indicator instead of mode buttons while modes load', () => {
    mockedModes.mockReturnValue(modesState({ isLoading: true }))

    renderPage()

    expect(screen.getByText('Loading insights...')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Most Polarizing' })).not.toBeInTheDocument()
  })

  it('opens a discovery view, hides browse controls, and lists supporting metrics', () => {
    mockedDiscovery.mockReturnValue(
      discoveryState({
        data: makeDiscovery({
          total: 2,
          items: [
            makeDiscoveryItem({
              canonical_creator_key: 'creator:7',
              display_name: 'Brian K. Vaughan',
              normalized_roles: ['writer'],
              average_rating: 4.5,
              ratings_count: 7,
              upcoming_count: 2,
              qualifying_metrics: {
                top_rating_rate: 30,
                acceptance_score: 4.2,
                hit_percentage: 50,
                issue_count: 7,
                spread_size: 3,
                depth_sample: 9,
                intensity: 3.25,
                badge: 'top',
              },
            }),
          ],
        }),
      }),
    )

    renderPage()
    fireEvent.click(screen.getByRole('button', { name: 'Most Consistently Loved' }))

    expect(screen.queryByLabelText('Search creators by name')).not.toBeInTheDocument()
    expect(screen.getByText('Showing 1 of 2 creators')).toBeInTheDocument()

    const link = screen.getByRole('link', { name: /Brian K\. Vaughan/ })
    expect(link).toHaveAttribute('href', '/creators/creator%3A7')
    expect(screen.getByText('7 rated issues')).toBeInTheDocument()
    expect(screen.getByText('4.5★')).toBeInTheDocument()
    expect(screen.getByText('2 unread')).toBeInTheDocument()

    for (const metric of ['30%', '4.2%', '50%', '7', '3', '9', '3.3', 'top']) {
      expect(screen.getByText(metric)).toBeInTheDocument()
    }
  })

  it('explains when no creators qualify for a discovery view', () => {
    mockedDiscovery.mockReturnValue(discoveryState({ data: makeDiscovery() }))

    renderPage()
    fireEvent.click(screen.getByRole('button', { name: 'Most Polarizing' }))

    expect(screen.getByText('No creators match this discovery view yet.')).toBeInTheDocument()
  })

  it('labels the discovery section before the response arrives', () => {
    renderPage()
    fireEvent.click(screen.getByRole('button', { name: 'Most Read' }))

    expect(screen.getByRole('heading', { name: 'Discovery' })).toBeInTheDocument()
  })

  it('shows placeholders while discovery results load', () => {
    mockedDiscovery.mockReturnValue(discoveryState({ data: makeDiscovery(), isPending: true }))

    renderPage()
    fireEvent.click(screen.getByRole('button', { name: 'Highest Top Rating Rate' }))

    expect(screen.getByLabelText('Loading discovery')).toBeInTheDocument()
  })

  it('shows a recoverable discovery error and retries', () => {
    const refetch = vi.fn()
    mockedDiscovery.mockReturnValue(
      discoveryState({ data: makeDiscovery(), isError: true, refetch }),
    )

    renderPage()
    fireEvent.click(screen.getByRole('button', { name: 'Great Average, Small Sample' }))

    expect(screen.getByText('Could not load discovery results')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(refetch).toHaveBeenCalled()
  })

  it('returns to browsing from the discovery header without losing the search state', () => {
    mockedDiscovery.mockReturnValue(discoveryState({ data: makeDiscovery() }))

    renderPage()
    const search = screen.getByLabelText('Search creators by name')
    fireEvent.change(search, { target: { value: 'vaughan' } })

    fireEvent.click(screen.getByRole('button', { name: 'Loved with Unread' }))
    expect(screen.queryByLabelText('Search creators by name')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Back to browse' }))
    const restoredSearch = screen.getByLabelText('Search creators by name')
    // SAFETY: the search control rendered by CreatorsPage is an HTMLInputElement.
    expect((restoredSearch as HTMLInputElement).value).toBe('')
  })

  it('switches between discovery and browsing with the browse control', () => {
    mockedDiscovery.mockReturnValue(discoveryState({ data: makeDiscovery() }))

    renderPage()

    // Already browsing: choosing Browse Creators is a harmless no-op.
    fireEvent.click(screen.getByRole('button', { name: 'Browse Creators' }))
    expect(screen.getByLabelText('Search creators by name')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Most Read' }))
    expect(screen.queryByLabelText('Search creators by name')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Browse Creators' }))
    expect(screen.getByLabelText('Search creators by name')).toBeInTheDocument()
  })

  it('selects and deselects creators directly from a discovery view', () => {
    mockedDiscovery.mockReturnValue(
      discoveryState({
        data: makeDiscovery({
          total: 2,
          items: [
            makeDiscoveryItem({ canonical_creator_key: 'creator:1', display_name: 'A One' }),
            makeDiscoveryItem({ canonical_creator_key: 'creator:2', display_name: 'B Two' }),
          ],
        }),
      }),
    )

    renderPage()
    fireEvent.click(screen.getByRole('button', { name: 'Most Consistently Loved' }))

    fireEvent.click(screen.getByLabelText('Select A One for comparison'))
    expect(screen.getByText('1 of 4 selected for comparison')).toBeInTheDocument()

    fireEvent.click(screen.getByLabelText('Select A One for comparison'))
    expect(screen.queryByText(/selected for comparison/)).not.toBeInTheDocument()
  })

  it('renders an unlinked, unrated discovery row when the key is not canonical', () => {
    mockedDiscovery.mockReturnValue(
      discoveryState({
        data: makeDiscovery({
          items: [
            makeDiscoveryItem({
              canonical_creator_key: 'Alex Kim',
              display_name: 'Alex Kim',
              normalized_roles: [],
              average_rating: null,
              ratings_count: 1,
              upcoming_count: 0,
              qualifying_metrics: {},
            }),
          ],
        }),
      }),
    )

    renderPage()
    fireEvent.click(screen.getByRole('button', { name: 'Most Consistently Loved' }))

    expect(screen.getByText('Alex Kim')).toBeInTheDocument()
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
    expect(screen.getByText('1 rated issue')).toBeInTheDocument()
    expect(screen.getByText('unrated')).toBeInTheDocument()
  })
})
