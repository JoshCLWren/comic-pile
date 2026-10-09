import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'

const { importSeriesSpy, searchSeriesSpy, invalidateSpy, toastSpy } = vi.hoisted(() => ({
  importSeriesSpy: vi.fn(),
  searchSeriesSpy: vi.fn(),
  invalidateSpy: vi.fn().mockResolvedValue(undefined),
  toastSpy: {
    toasts: [],
    showToast: vi.fn(() => 'toast-id'),
    removeToast: vi.fn(),
  },
}))

vi.mock('../services/api-comicvine', () => ({
  comicVineApi: {
    searchSeries: searchSeriesSpy,
    importSeries: importSeriesSpy,
  },
}))

vi.mock('../query/cacheEffects', () => ({
  invalidateAfterQueueMutation: invalidateSpy,
}))

vi.mock('../contexts/useToast', () => ({
  useToast: () => toastSpy,
}))

vi.mock('../components/Modal', () => ({
  default: ({ isOpen, title, children, size }: { isOpen: boolean; title: string; children: ReactNode; size?: string }) =>
    isOpen ? <div role="dialog" data-modal-size={size}><h2>{title}</h2>{children}</div> : null,
}))

import AddSeriesFromComicVineDialog from '../components/AddSeriesFromComicVineDialog'
import type { ComicVineSeriesResult } from '../services/api-comicvine'

const stormwatch: ComicVineSeriesResult = {
  comicvine_volume_id: 42,
  name: 'Stormwatch',
  publisher: 'WildStorm',
  start_year: 1993,
  issue_count: 12,
  site_detail_url: null,
  image_url: null,
}

const saga: ComicVineSeriesResult = {
  comicvine_volume_id: 99,
  name: 'Saga',
  publisher: 'Image',
  start_year: 2012,
  issue_count: 3,
  site_detail_url: null,
  image_url: null,
}

const page = (
  results: typeof stormwatch[],
  overrides: Partial<{ has_more: boolean; next_offset: number | null; offset: number }> = {},
) => ({
  query: 'storm',
  results,
  total_available: 20,
  offset: 0,
  limit: 10,
  has_more: false,
  next_offset: null,
  ...overrides,
})

function defaultProps(overrides: Partial<{
  isOpen: boolean
  onClose: () => void
  onAdded: (threadId: number) => void
}> = {}) {
  return {
    isOpen: true,
    onClose: vi.fn(),
    onAdded: vi.fn(),
    ...overrides,
  }
}

async function search(query: string) {
  const input = screen.getByPlaceholderText('Search series title (e.g., Batman, Saga, One Piece)')
  fireEvent.change(input, { target: { value: query } })
  return input
}

describe('AddSeriesFromComicVineDialog search step', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    toastSpy.showToast.mockClear()
    invalidateSpy.mockClear()
    invalidateSpy.mockResolvedValue(undefined)
    searchSeriesSpy.mockReset()
    importSeriesSpy.mockReset()
    searchSeriesSpy.mockResolvedValue(page([stormwatch]))
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('prompts for a title before any search is performed', () => {
    render(<AddSeriesFromComicVineDialog {...defaultProps()} />)

    expect(screen.getByText('Type a series name to search ComicVine')).toBeInTheDocument()
    expect(screen.queryByText('No series found. Try a different search term.')).not.toBeInTheDocument()
    expect(searchSeriesSpy).not.toHaveBeenCalled()
  })

  it('searches ComicVine after the debounce interval and renders disambiguating metadata', async () => {
    render(<AddSeriesFromComicVineDialog {...defaultProps()} />)

    await search('Stormwatch')

    await waitFor(() => expect(searchSeriesSpy).toHaveBeenCalledWith('Stormwatch', 10, 0))
    expect(screen.getByText('Stormwatch')).toBeInTheDocument()
    expect(screen.getByText('WildStorm · 1993 · 12 issues')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Stormwatch - WildStorm, 1993, 12 issues' })).toBeInTheDocument()
  })

  it('trims the query before sending it to the provider', async () => {
    render(<AddSeriesFromComicVineDialog {...defaultProps()} />)

    await search('  Stormwatch  ')

    await waitFor(() => expect(searchSeriesSpy).toHaveBeenCalledWith('Stormwatch', 10, 0))
  })

  it('searches immediately when Enter is pressed', async () => {
    render(<AddSeriesFromComicVineDialog {...defaultProps()} />)

    const input = await search('Stormwatch')
    fireEvent.keyDown(input, { key: 'Enter' })

    await waitFor(() => expect(searchSeriesSpy).toHaveBeenCalledWith('Stormwatch', 10, 0))
  })

  it('coalesces a debounced search and an Enter press into one provider call', async () => {
    render(<AddSeriesFromComicVineDialog {...defaultProps()} />)

    const input = await search('Stormwatch')
    fireEvent.keyDown(input, { key: 'Enter' })
    await waitFor(() => expect(searchSeriesSpy).toHaveBeenCalledTimes(1))

    // The cleared debounce timer must not fire a duplicate request.
    await new Promise((resolve) => setTimeout(resolve, 500))
    expect(searchSeriesSpy).toHaveBeenCalledTimes(1)
  })

  it('clears results and pagination when the query is emptied', async () => {
    render(<AddSeriesFromComicVineDialog {...defaultProps()} />)

    const input = await search('Stormwatch')
    await waitFor(() => expect(screen.getByText('Stormwatch')).toBeInTheDocument())

    fireEvent.change(input, { target: { value: '' } })

    await waitFor(() => expect(screen.queryByText('Stormwatch')).not.toBeInTheDocument())
    expect(screen.getByText('Type a series name to search ComicVine')).toBeInTheDocument()
  })

  it('ignores a whitespace-only query without calling the provider', async () => {
    render(<AddSeriesFromComicVineDialog {...defaultProps()} />)

    await search('   ')

    await waitFor(() =>
      expect(screen.getByText('Type a series name to search ComicVine')).toBeInTheDocument(),
    )
    expect(searchSeriesSpy).not.toHaveBeenCalled()
  })

  it('surfaces a provider search failure and keeps manual re-entry possible', async () => {
    searchSeriesSpy.mockRejectedValue(new Error('Network error'))

    render(<AddSeriesFromComicVineDialog {...defaultProps()} />)

    await search('Stormwatch')

    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent('Failed to search ComicVine. Please try again.'),
    )
    expect(screen.getByPlaceholderText('Search series title (e.g., Batman, Saga, One Piece)')).toBeInTheDocument()
    expect(screen.queryByText('No series found. Try a different search term.')).not.toBeInTheDocument()
  })

  it('shows the no-results state only after a completed empty search', async () => {
    searchSeriesSpy.mockResolvedValue(page([]))

    render(<AddSeriesFromComicVineDialog {...defaultProps()} />)

    await search('Nonexistent')

    await waitFor(() =>
      expect(screen.getByText('No series found. Try a different search term.')).toBeInTheDocument(),
    )
  })

  it('renders a result without metadata using the bare series name', async () => {
    searchSeriesSpy.mockResolvedValue(
      page([{ ...saga, publisher: null, start_year: null, issue_count: null }]),
    )

    render(<AddSeriesFromComicVineDialog {...defaultProps()} />)

    await search('Saga')

    await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())
    expect(screen.getByRole('button', { name: 'Saga' })).toBeInTheDocument()
  })

  it('renders a series cover image when the provider supplies one', async () => {
    searchSeriesSpy.mockResolvedValue(page([{ ...stormwatch, image_url: 'https://example.com/series.jpg' }]))

    const { container } = render(<AddSeriesFromComicVineDialog {...defaultProps()} />)

    await search('Stormwatch')

    await waitFor(() => expect(screen.getByText('Stormwatch')).toBeInTheDocument())
    expect(container.querySelectorAll('img').length).toBeGreaterThanOrEqual(1)
  })

  it('stale debounced searches do not overwrite newer query results', async () => {
    searchSeriesSpy.mockResolvedValue(page([stormwatch]))

    render(<AddSeriesFromComicVineDialog {...defaultProps()} />)

    const input = await search('Stormwatch')
    await waitFor(() => expect(searchSeriesSpy).toHaveBeenCalledTimes(1))

    // Type a new query while the first request is still in flight.
    searchSeriesSpy.mockImplementation(
      () =>
        new Promise((resolve) => {
          setTimeout(() => resolve(page([saga])), 50)
        }),
    )
    fireEvent.change(input, { target: { value: 'Saga' } })

    await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())
    expect(screen.queryByText('Stormwatch')).not.toBeInTheDocument()
  })

  it('clears the pending debounce timer when the dialog unmounts', async () => {
    const clearTimeoutSpy = vi.spyOn(globalThis, 'clearTimeout')

    const { unmount } = render(<AddSeriesFromComicVineDialog {...defaultProps()} />)
    await search('Stormwatch')
    unmount()

    expect(clearTimeoutSpy).toHaveBeenCalled()
    clearTimeoutSpy.mockRestore()
  })
})

describe('AddSeriesFromComicVineDialog load-more pagination', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    toastSpy.showToast.mockClear()
    invalidateSpy.mockClear()
    invalidateSpy.mockResolvedValue(undefined)
    searchSeriesSpy.mockReset()
    importSeriesSpy.mockReset()
  })

  it('appends the next page without duplicating series already shown', async () => {
    searchSeriesSpy
      .mockResolvedValueOnce(
        page([{ ...stormwatch, comicvine_volume_id: 1, name: 'Storm Series' }, saga], {
          has_more: true,
          next_offset: 2,
        }),
      )
      .mockResolvedValueOnce(
        page([saga, { ...stormwatch, comicvine_volume_id: 3, name: 'Storm Special' }], {
          has_more: false,
          next_offset: null,
          offset: 2,
        }),
      )

    render(<AddSeriesFromComicVineDialog {...defaultProps()} />)
    await search('Storm')

    await waitFor(() => expect(screen.getByText('Storm Series')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'Load more' }))

    await waitFor(() => expect(screen.getByText('Storm Special')).toBeInTheDocument())
    expect(searchSeriesSpy).toHaveBeenLastCalledWith('Storm', 10, 2)
    expect(screen.getAllByText('Saga')).toHaveLength(1)
    expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument()
  })

  it('does not request the next page while a search is already running', async () => {
    searchSeriesSpy.mockResolvedValueOnce(
      page([stormwatch], { has_more: true, next_offset: 1 }),
    )

    render(<AddSeriesFromComicVineDialog {...defaultProps()} />)
    await search('Stormwatch')

    await waitFor(() => expect(screen.getByText('Stormwatch')).toBeInTheDocument())
    const loadMore = screen.getByRole('button', { name: 'Load more' })
    fireEvent.click(loadMore)
    fireEvent.click(loadMore)

    await waitFor(() => expect(searchSeriesSpy).toHaveBeenCalledTimes(2))
  })

  it('keeps already-loaded results visible when loading the next page fails', async () => {
    searchSeriesSpy
      .mockResolvedValueOnce(page([stormwatch], { has_more: true, next_offset: 1 }))
      .mockRejectedValueOnce(new Error('Network error'))

    render(<AddSeriesFromComicVineDialog {...defaultProps()} />)
    await search('Stormwatch')

    await waitFor(() => expect(screen.getByText('Stormwatch')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'Load more' }))

    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent('Failed to search ComicVine. Please try again.'),
    )
    expect(screen.getByText('Stormwatch')).toBeInTheDocument()
  })

  it('hides Load more when the provider reports no further pages', async () => {
    searchSeriesSpy.mockResolvedValue(page([stormwatch], { has_more: false, next_offset: null }))

    render(<AddSeriesFromComicVineDialog {...defaultProps()} />)
    await search('Stormwatch')

    await waitFor(() => expect(screen.getByText('Stormwatch')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument()
  })

  it('hides Load more when the provider omits a next offset', async () => {
    searchSeriesSpy.mockResolvedValue(page([stormwatch], { has_more: true, next_offset: null }))

    render(<AddSeriesFromComicVineDialog {...defaultProps()} />)
    await search('Stormwatch')

    await waitFor(() => expect(screen.getByText('Stormwatch')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument()
  })
})

describe('AddSeriesFromComicVineDialog confirm and add', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    toastSpy.showToast.mockClear()
    toastSpy.showToast.mockImplementation(() => 'toast-id')
    invalidateSpy.mockClear()
    invalidateSpy.mockResolvedValue(undefined)
    searchSeriesSpy.mockReset()
    importSeriesSpy.mockReset()
    searchSeriesSpy.mockResolvedValue(page([stormwatch]))
    importSeriesSpy.mockResolvedValue({
      thread_id: 501,
      series_name: 'Stormwatch',
      comicvine_volume_id: 42,
      total_issues_in_series: 12,
      issues_adopted: 12,
      issues_skipped: 0,
      issues_conflict: 0,
      issue_results: [],
      reading_order_id: null,
      position: null,
      total_items: null,
      thread_created: true,
    })
  })

  async function selectStormwatch() {
    await search('Stormwatch')
    await waitFor(() => expect(screen.getByText('Stormwatch')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /Stormwatch - WildStorm/ }))
    await waitFor(() => expect(screen.getByTestId('add-series-confirm-card')).toBeInTheDocument())
  }

  it('shows a compact confirmation instead of a duplicate data-entry form', async () => {
    render(<AddSeriesFromComicVineDialog {...defaultProps()} />)
    await selectStormwatch()

    expect(screen.getByTestId('add-series-confirm-card')).toHaveTextContent('Stormwatch')
    expect(
      screen.getByText('This will create a new series in your queue with all 12 issues from the ComicVine volume.'),
    ).toBeInTheDocument()
    expect(screen.queryByPlaceholderText('Search series title (e.g., Batman, Saga, One Piece)')).not.toBeInTheDocument()
    // Provider facts are supplied, so no manual title/issue-count entry is shown.
    expect(screen.queryByRole('textbox', { name: /title/i })).not.toBeInTheDocument()
  })

  it('adds the selected series without any manual source-fact entry', async () => {
    const onAdded = vi.fn()
    const onClose = vi.fn()

    render(<AddSeriesFromComicVineDialog {...defaultProps({ onAdded, onClose })} />)
    await selectStormwatch()

    fireEvent.click(screen.getByRole('button', { name: 'Add Series to ComicPile' }))

    await waitFor(() => expect(importSeriesSpy).toHaveBeenCalledTimes(1))
    expect(importSeriesSpy).toHaveBeenCalledWith({ comicvine_volume_id: 42, already_read_count: 0 })
    await waitFor(() => expect(onAdded).toHaveBeenCalledWith(501))
    expect(invalidateSpy).toHaveBeenCalled()
    expect(toastSpy.showToast).toHaveBeenCalledWith(
      'Added "Stormwatch" to ComicPile (12 issues)',
      'success',
    )
    expect(onClose).toHaveBeenCalled()
  })

  it('passes optional already-read personal state separately from provider facts', async () => {
    render(<AddSeriesFromComicVineDialog {...defaultProps()} />)
    await selectStormwatch()

    fireEvent.change(screen.getByLabelText('Issues already read (optional)'), {
      target: { value: '4' },
    })
    expect(
      screen.getByText('First 4 of 12 issues will be marked as read'),
    ).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Add Series to ComicPile' }))

    await waitFor(() =>
      expect(importSeriesSpy).toHaveBeenCalledWith({ comicvine_volume_id: 42, already_read_count: 4 }),
    )
  })

  it('clamps the already-read count to the selected volume issue count', async () => {
    render(<AddSeriesFromComicVineDialog {...defaultProps()} />)
    await selectStormwatch()

    const alreadyRead = screen.getByLabelText('Issues already read (optional)')
    expect(alreadyRead).toHaveAttribute('max', '12')

    fireEvent.change(alreadyRead, { target: { value: '99' } })
    await waitFor(() => expect(alreadyRead).toHaveValue(12))

    fireEvent.change(alreadyRead, { target: { value: '-5' } })
    await waitFor(() => expect(alreadyRead).toHaveValue(0))

    fireEvent.change(alreadyRead, { target: { value: '' } })
    await waitFor(() => expect(alreadyRead).toHaveValue(0))
  })

  it('hides the already-read control when the provider reports no issue count', async () => {
    searchSeriesSpy.mockResolvedValue(page([{ ...saga, issue_count: null }]))

    render(<AddSeriesFromComicVineDialog {...defaultProps()} />)
    await search('Saga')
    await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'Saga - Image, 2012' }))

    await waitFor(() => expect(screen.getByTestId('add-series-confirm-card')).toBeInTheDocument())
    expect(screen.queryByLabelText('Issues already read (optional)')).not.toBeInTheDocument()
    expect(
      screen.getByText('This will create a new series in your queue with all ? issues from the ComicVine volume.'),
    ).toBeInTheDocument()
  })

  it('renders a provider cover on the confirmation card', async () => {
    searchSeriesSpy.mockResolvedValue(page([{ ...stormwatch, image_url: 'https://example.com/series.jpg' }]))

    const { container } = render(<AddSeriesFromComicVineDialog {...defaultProps()} />)
    await selectStormwatch()

    expect(container.querySelectorAll('img').length).toBeGreaterThanOrEqual(1)
  })

  it('keeps the dialog open and reports the failure when the import fails', async () => {
    importSeriesSpy.mockRejectedValue(new Error('ComicVine provider failure'))
    const onClose = vi.fn()
    const onAdded = vi.fn()

    render(<AddSeriesFromComicVineDialog {...defaultProps({ onClose, onAdded })} />)
    await selectStormwatch()

    fireEvent.click(screen.getByRole('button', { name: 'Add Series to ComicPile' }))

    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('ComicVine provider failure'))
    expect(screen.getByRole('button', { name: 'Add Series to ComicPile' })).toBeEnabled()
    expect(onClose).not.toHaveBeenCalled()
    expect(onAdded).not.toHaveBeenCalled()
  })

  it('falls back to a generic message when the import failure is not an Error', async () => {
    importSeriesSpy.mockRejectedValue('boom')

    render(<AddSeriesFromComicVineDialog {...defaultProps()} />)
    await selectStormwatch()

    fireEvent.click(screen.getByRole('button', { name: 'Add Series to ComicPile' }))

    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent('Failed to add series from ComicVine'),
    )
  })

  it('does not add anything when the confirm step has no selection', async () => {
    render(<AddSeriesFromComicVineDialog {...defaultProps()} />)
    await selectStormwatch()

    fireEvent.click(screen.getByRole('button', { name: '← Back to search' }))
    await waitFor(() => expect(screen.getByPlaceholderText(/Search series title/)).toBeInTheDocument())

    expect(importSeriesSpy).not.toHaveBeenCalled()
  })

  it('returns to search and clears the selection when the user backs out', async () => {
    render(<AddSeriesFromComicVineDialog {...defaultProps()} />)
    await selectStormwatch()

    fireEvent.click(screen.getByRole('button', { name: '← Back to search' }))

    await waitFor(() => expect(screen.queryByTestId('add-series-confirm-card')).not.toBeInTheDocument())
    expect(screen.getByPlaceholderText(/Search series title/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Add Series to ComicPile' })).not.toBeInTheDocument()
  })

  it('does not carry the previous series already-read count into a new selection', async () => {
    render(<AddSeriesFromComicVineDialog {...defaultProps()} />)
    await selectStormwatch()

    fireEvent.change(screen.getByLabelText('Issues already read (optional)'), {
      target: { value: '9' },
    })
    await waitFor(() => expect(screen.getByLabelText('Issues already read (optional)')).toHaveValue(9))

    // Back out and pick a shorter run: personal progress must not leak across runs.
    searchSeriesSpy.mockResolvedValue(page([{ ...saga, issue_count: 2 }]))
    fireEvent.click(screen.getByRole('button', { name: '← Back to search' }))
    await waitFor(() => expect(screen.getByPlaceholderText(/Search series title/)).toBeInTheDocument())
    fireEvent.change(screen.getByPlaceholderText(/Search series title/), { target: { value: 'Saga' } })
    await waitFor(() => expect(screen.getByRole('button', { name: /Saga - Image/ })).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /Saga - Image/ }))

    await waitFor(() => expect(screen.getByTestId('add-series-confirm-card')).toBeInTheDocument())
    expect(screen.getByLabelText('Issues already read (optional)')).toHaveValue(0)

    fireEvent.click(screen.getByRole('button', { name: 'Add Series to ComicPile' }))
    await waitFor(() =>
      expect(importSeriesSpy).toHaveBeenCalledWith({ comicvine_volume_id: 99, already_read_count: 0 }),
    )
  })

  it('reports an additive retry against an existing series honestly', async () => {
    importSeriesSpy.mockResolvedValue({
      thread_id: 501,
      series_name: 'Stormwatch',
      comicvine_volume_id: 42,
      total_issues_in_series: 12,
      issues_adopted: 4,
      issues_skipped: 8,
      issues_conflict: 0,
      issue_results: [],
      reading_order_id: null,
      position: null,
      total_items: null,
      thread_created: false,
    })

    render(<AddSeriesFromComicVineDialog {...defaultProps()} />)
    await selectStormwatch()

    fireEvent.click(screen.getByRole('button', { name: 'Add Series to ComicPile' }))

    await waitFor(() =>
      expect(toastSpy.showToast).toHaveBeenCalledWith(
        'Added 4 more issues to "Stormwatch"',
        'success',
      ),
    )
  })
})

describe('AddSeriesFromComicVineDialog open-state handling', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    toastSpy.showToast.mockClear()
    invalidateSpy.mockClear()
    invalidateSpy.mockResolvedValue(undefined)
    searchSeriesSpy.mockReset()
    importSeriesSpy.mockReset()
    searchSeriesSpy.mockResolvedValue(page([stormwatch]))
  })

  it('renders nothing while closed', () => {
    render(<AddSeriesFromComicVineDialog {...defaultProps({ isOpen: false })} />)

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('resets search, selection, and personal state when reopened', async () => {
    importSeriesSpy.mockRejectedValue(new Error('nope'))

    const { rerender } = render(<AddSeriesFromComicVineDialog {...defaultProps()} />)

    await search('Stormwatch')
    await waitFor(() => expect(screen.getByText('Stormwatch')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /Stormwatch - WildStorm/ }))
    await waitFor(() => expect(screen.getByTestId('add-series-confirm-card')).toBeInTheDocument())
    fireEvent.change(screen.getByLabelText('Issues already read (optional)'), {
      target: { value: '5' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Add Series to ComicPile' }))
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())

    rerender(<AddSeriesFromComicVineDialog {...defaultProps({ isOpen: false })} />)
    rerender(<AddSeriesFromComicVineDialog {...defaultProps({ isOpen: true })} />)

    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())
    expect(screen.getByPlaceholderText(/Search series title/)).toHaveValue('')
    expect(screen.getByText('Type a series name to search ComicVine')).toBeInTheDocument()
  })
})