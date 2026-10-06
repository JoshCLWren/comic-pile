import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation, useSearchParams } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import CreatorsPage from '../pages/CreatorsPage'
import { useCreatorsList } from '../hooks/useCreatorsList'
import type { CreatorListSelection, CreatorsListState } from '../hooks/useCreatorsList'
import type { CreatorListItem } from '../services/api-creators'
import { cast } from '../utils/cast'

vi.mock('../hooks/useCreatorsList', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../hooks/useCreatorsList')>()),
  useCreatorsList: vi.fn(),
}))

vi.mock('../hooks/useDebounce', () => ({
  useDebounce: <T,>(value: T) => value,
}))

const mockedHook = vi.mocked(useCreatorsList)

const originalMatchMedia = window.matchMedia

/** Pretend the viewport is in the band where `min-width: 768px` matches. */
function useWideViewport(): void {
  window.matchMedia = vi.fn((query: string) =>
    cast<MediaQueryList>({
      matches: query.includes('min-width: 768px'),
      media: query,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(() => false),
    }),
  )
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

function LocationProbe() {
  const location = useLocation()
  return <div data-testid="location-search">{location.search}</div>
}

function renderPage(
  extraRoutes?: { path: string; element: React.ReactNode }[],
  initialEntry = '/creators',
) {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route
          path="/creators"
          element={
            <>
              <CreatorsPage />
              <LocationProbe />
            </>
          }
        />
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
})

afterEach(() => {
  window.matchMedia = originalMatchMedia
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

describe('CreatorsPage bounded browse filters', () => {
  it('keeps the secondary filter row collapsed until it is asked for', () => {
    renderPage()

    const toggle = screen.getByRole('button', { name: 'More filters' })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByLabelText('Role')).not.toBeInTheDocument()

    fireEvent.click(toggle)

    expect(screen.getByRole('button', { name: 'Hide filters' })).toHaveAttribute(
      'aria-expanded',
      'true',
    )
    expect(screen.getByLabelText('Role')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Hide filters' }))
    expect(screen.queryByLabelText('Role')).not.toBeInTheDocument()
  })

  it('shows the secondary filter row by default once the viewport is wide enough', () => {
    useWideViewport()

    renderPage()

    expect(screen.getByRole('button', { name: 'Hide filters' })).toHaveAttribute(
      'aria-expanded',
      'true',
    )
    expect(screen.getByLabelText('Role')).toBeInTheDocument()
  })

  it('restores every bounded filter from the URL', () => {
    const seen: CreatorListSelection[] = []
    mockedHook.mockImplementation((selection) => {
      seen.push(selection)
      return baseState()
    })
    useWideViewport()

    renderPage(undefined, '/creators?role=penciler&min_rating=4&max_rating=4.5&unread=true')

    expect(seen.at(-1)).toMatchObject({
      role: 'penciler',
      minRating: 4,
      maxRating: 4.5,
      hasUnreadWork: true,
    })
    expect(screen.getByLabelText('Role')).toHaveValue('penciler')
    expect(screen.getByLabelText('Minimum average rating')).toHaveValue(4)
    expect(screen.getByLabelText('Maximum average rating')).toHaveValue(4.5)
    expect(screen.getByLabelText('Unread work')).toHaveValue('true')
  })

  it('records every bounded filter in the URL so the selection survives navigation', () => {
    const seen: CreatorListSelection[] = []
    mockedHook.mockImplementation((selection) => {
      seen.push(selection)
      return baseState()
    })
    useWideViewport()

    renderPage()

    fireEvent.change(screen.getByLabelText('Role'), { target: { value: 'writer' } })
    fireEvent.change(screen.getByLabelText('Minimum average rating'), { target: { value: '4' } })
    fireEvent.change(screen.getByLabelText('Maximum average rating'), { target: { value: '4.5' } })
    fireEvent.change(screen.getByLabelText('Unread work'), { target: { value: 'true' } })

    const search = screen.getByTestId('location-search').textContent ?? ''
    expect(search).toContain('role=writer')
    expect(search).toContain('min_rating=4')
    expect(search).toContain('max_rating=4.5')
    expect(search).toContain('unread=true')
    expect(seen.at(-1)).toMatchObject({
      role: 'writer',
      minRating: 4,
      maxRating: 4.5,
      hasUnreadWork: true,
    })
  })

  it('drops a filter again when the control is returned to its neutral value', () => {
    const seen: CreatorListSelection[] = []
    mockedHook.mockImplementation((selection) => {
      seen.push(selection)
      return baseState()
    })
    useWideViewport()

    renderPage()

    fireEvent.change(screen.getByLabelText('Role'), { target: { value: 'artist' } })
    fireEvent.change(screen.getByLabelText('Minimum average rating'), { target: { value: '3' } })
    fireEvent.change(screen.getByLabelText('Unread work'), { target: { value: 'true' } })

    fireEvent.change(screen.getByLabelText('Role'), { target: { value: '' } })
    fireEvent.change(screen.getByLabelText('Minimum average rating'), { target: { value: '' } })
    fireEvent.change(screen.getByLabelText('Unread work'), { target: { value: '' } })

    expect(screen.getByTestId('location-search').textContent).toBe('')
    expect(seen.at(-1)).toMatchObject({
      role: undefined,
      minRating: undefined,
      maxRating: undefined,
      hasUnreadWork: undefined,
    })
  })

  it('ignores a hand-edited rating filter outside the personal 0-5 scale', () => {
    const seen: CreatorListSelection[] = []
    mockedHook.mockImplementation((selection) => {
      seen.push(selection)
      return baseState()
    })
    useWideViewport()

    renderPage(undefined, '/creators?min_rating=9&max_rating=-3')

    expect(seen.at(-1)).toMatchObject({ minRating: undefined, maxRating: undefined })
    expect(screen.getByLabelText('Minimum average rating')).toHaveValue(null)
    expect(screen.getByLabelText('Maximum average rating')).toHaveValue(null)
  })

  it('clears every bounded filter at once', () => {
    const seen: CreatorListSelection[] = []
    mockedHook.mockImplementation((selection) => {
      seen.push(selection)
      return baseState({
        items: [makeItem({ canonical_creator_key: 'creator:1' })],
        total: 1,
      })
    })
    useWideViewport()

    renderPage(undefined, '/creators?role=writer&min_rating=4&max_rating=4.5&unread=false')

    expect(screen.getByRole('note')).toHaveTextContent('4 active')
    fireEvent.click(screen.getByRole('button', { name: 'Clear filters' }))

    expect(screen.getByTestId('location-search').textContent).toBe('')
    expect(seen.at(-1)).toMatchObject({
      role: undefined,
      minRating: undefined,
      maxRating: undefined,
      hasUnreadWork: undefined,
    })
  })

  it('explains an empty filtered result and offers a way out', () => {
    useWideViewport()

    renderPage(undefined, '/creators?role=colorist')

    expect(screen.getByText('No creators match the current filters.')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Clear filters' }))
    expect(screen.getByTestId('location-search').textContent).toBe('')
  })

  it('offers only the bounded role vocabulary the server exposes', () => {
    useWideViewport()

    renderPage()

    // SAFETY: getByLabelText('Role') returns the role select rendered by CreatorsPage, so the element is an HTMLSelectElement.
    const select = screen.getByLabelText('Role') as HTMLSelectElement
    expect([...select.options].map((option) => option.value)).toEqual([
      '',
      'writer',
      'artist',
      'penciler',
      'inker',
      'colorist',
      'letterer',
      'cover artist',
      'editor',
    ])
  })
})
