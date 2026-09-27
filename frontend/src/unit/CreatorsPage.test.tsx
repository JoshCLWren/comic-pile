import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CreatorsPage from '../pages/CreatorsPage'
import { useCreatorsList } from '../hooks/useCreatorsList'
import type { CreatorListSelection, CreatorsListState } from '../hooks/useCreatorsList'
import type { CreatorListItem } from '../services/api-creators'

vi.mock('../hooks/useCreatorsList', () => ({
  useCreatorsList: vi.fn(),
}))

vi.mock('../hooks/useDebounce', () => ({
  useDebounce: <T,>(value: T) => value,
}))

const mockedHook = vi.mocked(useCreatorsList)

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
})
