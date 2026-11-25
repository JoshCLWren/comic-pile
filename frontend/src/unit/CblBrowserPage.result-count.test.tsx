import { act, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import {
  browsePage,
  mockBrowse,
  queryClient,
  renderPage,
  searchPage,
  source,
} from './CblBrowserPage.fixture'
import { queryKeys } from '../query/queryKeys'

const secondSource = { ...source, id: 8, name: 'Second Universe' }
const countLine = () => screen.getByTestId('cbl-result-count')

async function expectInitialCatalogCount(): Promise<void> {
  await waitFor(() => expect(countLine()).toHaveTextContent('13 of 13 source lists'))
}

describe('CblBrowserPage source list result count (#3614)', () => {
  it('includes direct and nested folder sources in the initial M of M count', async () => {
    mockBrowse.mockResolvedValue(browsePage({
      folders: [
        { name: 'DC', path: 'DC', direct_list_count: 4, total_list_count: 40 },
        { name: 'Marvel', path: 'Marvel', direct_list_count: 5, total_list_count: 97 },
      ],
      items: [source],
      total: 1,
      catalog_total: 138,
      total_pages: 1,
    }))
    renderPage()

    await waitFor(() => expect(countLine()).toHaveTextContent('138 of 138 source lists'))
    expect(screen.getByTestId('cbl-catalog-total')).toHaveTextContent(
      '138 sources in the shared CBL catalog across 2 folders',
    )
    expect(screen.getByText('Showing 1–1 of 1 source')).toBeInTheDocument()
  })

  it('shows M of M initially, keeps it while typing, and restores it on Clear', async () => {
    const user = userEvent.setup()
    mockBrowse.mockResolvedValue(browsePage({ total: 13, catalog_total: 13 }))
    renderPage()
    await expectInitialCatalogCount()

    await user.type(screen.getByLabelText('Search source lists'), 'x-men')
    // CBL search remains explicitly submitted; a draft does not own the count.
    expect(countLine()).toHaveTextContent('13 of 13 source lists')

    mockBrowse.mockResolvedValue({ ...searchPage('x-men', [source]), catalog_total: 13 })
    await user.keyboard('{Enter}')
    await waitFor(() => expect(countLine()).toHaveTextContent('1 of 13 source lists'))

    await user.click(screen.getByRole('button', { name: 'Clear search' }))
    await expectInitialCatalogCount()
  })

  it('shows N of M for Search and uses the whole shared catalog denominator', async () => {
    const user = userEvent.setup()
    mockBrowse.mockResolvedValue(browsePage({ total: 13, catalog_total: 13 }))
    renderPage()
    await expectInitialCatalogCount()

    mockBrowse.mockResolvedValue({
      ...searchPage('x-men', [source, secondSource]),
      catalog_total: 13,
    })
    await user.type(screen.getByLabelText('Search source lists'), 'x-men')
    await user.click(screen.getByRole('button', { name: 'Search' }))

    await waitFor(() => expect(countLine()).toHaveTextContent('2 of 13 source lists'))
    expect(screen.getByRole('button', { name: /Ultimate Universe/ })).toBeInTheDocument()
  })

  it('switches from a folder M of M scope to the global search denominator', async () => {
    const user = userEvent.setup()
    mockBrowse.mockResolvedValue(browsePage({ folder: 'Marvel', total: 2, catalog_total: 8 }))
    renderPage('/cbl-sources?folder=Marvel')
    await waitFor(() => expect(countLine()).toHaveTextContent('2 of 2 source lists'))

    mockBrowse.mockResolvedValue({ ...searchPage('x-men', [source]), catalog_total: 8 })
    await user.type(screen.getByLabelText('Search source lists'), 'x-men')
    await user.click(screen.getByRole('button', { name: 'Search' }))
    await waitFor(() => expect(countLine()).toHaveTextContent('1 of 8 source lists'))
  })

  it('shows 0 of M beside the existing empty state', async () => {
    const user = userEvent.setup()
    mockBrowse.mockResolvedValue(browsePage({ total: 13, catalog_total: 13 }))
    renderPage()
    await expectInitialCatalogCount()

    mockBrowse.mockResolvedValue({ ...searchPage('nothing', []), catalog_total: 13 })
    await user.type(screen.getByLabelText('Search source lists'), 'nothing')
    await user.click(screen.getByRole('button', { name: 'Search' }))

    await waitFor(() => expect(screen.getByText('No matching source lists found.')).toBeInTheDocument())
    expect(countLine()).toHaveTextContent('0 of 13 source lists')
  })

  it('uses the whole match total on a deep-linked page, not its visible row count', async () => {
    mockBrowse.mockResolvedValue({
      ...searchPage('marvel', [source, secondSource]),
      page: 2,
      total: 133,
      total_pages: 3,
      has_next: true,
      catalog_total: 200,
    })
    renderPage('/cbl-sources?q=marvel&page=2')

    await waitFor(() => expect(countLine()).toHaveTextContent('133 of 200 source lists'))
    expect(screen.getByText('Showing 51–52 of 133 sources')).toBeInTheDocument()
  })

  it('does not restate old totals or page counts while a replacement request is pending', async () => {
    const user = userEvent.setup()
    mockBrowse.mockResolvedValue(browsePage({ total: 13, catalog_total: 13 }))
    renderPage()
    await expectInitialCatalogCount()

    let resolveSearch: (page: ReturnType<typeof searchPage>) => void = () => undefined
    mockBrowse.mockImplementationOnce(
      () => new Promise((resolve) => { resolveSearch = resolve }),
    )
    await user.type(screen.getByLabelText('Search source lists'), 'x-men')
    await user.click(screen.getByRole('button', { name: 'Search' }))

    await waitFor(() => expect(countLine()).toHaveTextContent('Updating source list count…'))
    expect(countLine()).not.toHaveTextContent('13 of 13 source lists')
    expect(screen.queryByText(/^Showing \d+–\d+ of /)).not.toBeInTheDocument()
    expect(screen.queryByText(/^Page \d+ of \d+$/)).not.toBeInTheDocument()

    resolveSearch({ ...searchPage('x-men', [source]), catalog_total: 13 })
    await waitFor(() => expect(countLine()).toHaveTextContent('1 of 13 source lists'))
  })

  it('withholds old totals and page ranges during a same-key refresh', async () => {
    let resolveRefresh: (page: ReturnType<typeof browsePage>) => void = () => undefined
    mockBrowse
      .mockResolvedValueOnce(browsePage({ total: 13, catalog_total: 13 }))
      .mockImplementationOnce(
        () => new Promise((resolve) => { resolveRefresh = resolve }),
      )
    renderPage()
    await expectInitialCatalogCount()

    act(() => {
      void queryClient.refetchQueries({
        queryKey: queryKeys.cblSources.browse('', '', 1),
        exact: true,
      })
    })

    await waitFor(() => expect(countLine()).toHaveTextContent('Updating source list count…'))
    expect(countLine()).not.toHaveTextContent('13 of 13 source lists')
    expect(screen.queryByText(/^Showing \d+–\d+ of /)).not.toBeInTheDocument()
    expect(screen.queryByText(/^Page \d+ of \d+$/)).not.toBeInTheDocument()

    await act(async () => {
      resolveRefresh(browsePage({ items: [source], total: 12, catalog_total: 12 }))
    })
    await waitFor(() => expect(countLine()).toHaveTextContent('12 of 12 source lists'))
    expect(screen.getByText('Showing 1–1 of 12 sources')).toBeInTheDocument()
  })

  it('keeps the newest query count when an older request settles late', async () => {
    const user = userEvent.setup()
    let resolveAlpha: (page: ReturnType<typeof searchPage>) => void = () => undefined
    mockBrowse
      .mockResolvedValueOnce(browsePage({ total: 13, catalog_total: 13 }))
      .mockImplementationOnce(
        () => new Promise((resolve) => { resolveAlpha = resolve }),
      )
      .mockResolvedValueOnce({ ...searchPage('beta', [source]), catalog_total: 13 })

    renderPage()
    await expectInitialCatalogCount()
    await user.type(screen.getByLabelText('Search source lists'), 'alpha')
    await user.click(screen.getByRole('button', { name: 'Search' }))
    await waitFor(() => expect(countLine()).toHaveTextContent('Updating source list count…'))

    await user.clear(screen.getByLabelText('Search source lists'))
    await user.type(screen.getByLabelText('Search source lists'), 'beta')
    await user.click(screen.getByRole('button', { name: 'Search' }))
    await waitFor(() => expect(countLine()).toHaveTextContent('1 of 13 source lists'))

    resolveAlpha({
      ...searchPage('alpha', [source, secondSource]),
      total: 2,
      catalog_total: 13,
    })
    await act(async () => {})
    expect(countLine()).toHaveTextContent('1 of 13 source lists')
  })

  it('shows an unavailable count after a failed replacement search', async () => {
    const user = userEvent.setup()
    mockBrowse
      .mockResolvedValueOnce(browsePage({ total: 13, catalog_total: 13 }))
      .mockRejectedValueOnce(new Error('Network error'))
    renderPage()
    await expectInitialCatalogCount()

    await user.type(screen.getByLabelText('Search source lists'), 'x-men')
    await user.click(screen.getByRole('button', { name: 'Search' }))

    await waitFor(() => expect(countLine()).toHaveTextContent('Source list count unavailable.'))
    expect(countLine()).not.toHaveTextContent('13 of 13 source lists')
    expect(screen.queryByText(/^Showing \d+–\d+ of /)).not.toBeInTheDocument()
  })

  it('exposes an initial error and the settled count as accessible status text', async () => {
    mockBrowse.mockRejectedValueOnce(new Error('Network error'))
    const { unmount } = renderPage()
    await waitFor(() => expect(countLine()).toHaveTextContent('Source list count unavailable.'))
    unmount()

    mockBrowse.mockResolvedValue(browsePage({ total: 13, catalog_total: 13 }))
    renderPage()
    await expectInitialCatalogCount()
    expect(countLine()).toHaveAttribute('role', 'status')
    expect(countLine()).toHaveAttribute('aria-live', 'polite')
    expect(countLine()).toHaveClass('min-h-4', 'text-xs')
  })
})
