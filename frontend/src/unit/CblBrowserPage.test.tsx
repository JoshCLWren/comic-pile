import {
  act,
  screen,
  waitFor,
} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {
  describe,
  expect,
  it,
} from 'vitest'
import type {
  CBLAdoptionPreview,
  CBLAdoptionPreviewEntry,
  CBLCatalogBrowsePage,
  CBLSourceListDiscoveryItem,
} from '../services/api-cbl-sources'
import {
  MISTER_MIRACLE_OVERLAP,
  SECOND_MISTER_MIRACLE_OVERLAP,
} from './readingGraphFixture'
import {
  mockBrowse,
  mockPreview,
  source,
  renderPage,
  browsePage,
  searchPage,
  preview,
  searchFor,
} from './CblBrowserPage.fixture'

describe('CblBrowserPage catalog', () => {
  it('browses the catalog root immediately without a search submission', async () => {
    renderPage()
    expect(screen.getByRole('heading', { name: 'CBL Sources' })).toBeInTheDocument()
    expect(screen.getByLabelText('Search source lists')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Search' })).toBeInTheDocument()
    await waitFor(() => {
      expect(mockBrowse).toHaveBeenCalledWith({
        folder: '',
        query: '',
        page: 1,
        pageSize: 50,
      })
    })
  })

  it('opens the deep-linked source list detail with its ordered positions', async () => {
    renderPage('/cbl-sources?list=7')
    const detail = await screen.findByTestId('cbl-source-detail')
    expect(detail).toHaveTextContent('Ultimate Reading Order')
    expect(detail).toHaveTextContent('4000-1')
    expect(detail).toHaveTextContent('4000-2')
    expect(detail).toHaveTextContent('vol 4000-vol-1')
  })

  it('does not open a source detail without a list parameter', () => {
    renderPage()
    expect(screen.queryByTestId('cbl-source-detail')).not.toBeInTheDocument()
  })

  it('searches and lists matching sources', async () => {
    const user = userEvent.setup()
    renderPage()
    await searchFor(user)
    expect(mockBrowse).toHaveBeenLastCalledWith({
      folder: '',
      query: 'ultimate',
      page: 1,
      pageSize: 50,
    })
    expect(screen.getByText('Ultimate Universe')).toBeInTheDocument()
    expect(screen.getByText(/JoshCLWren\/CBL-ReadingLists/)).toBeInTheDocument()
    // #3939: the raw .cbl path stays out of the default search row.
    expect(screen.queryByText('Ultimate.cbl')).not.toBeInTheDocument()
  })

  it('hides filesystem mirror paths from source cards (#3365)', async () => {
    const user = userEvent.setup()
    const leaked: CBLSourceListDiscoveryItem = {
      ...source,
      source_path: '/mnt/bigdata/CBL-ReadingLists/Marvel/Ultimate.cbl',
      source_repository: '/mnt/bigdata/CBL-ReadingLists',
    }
    mockBrowse.mockResolvedValue(searchPage('ultimate', [leaked]))
    renderPage()
    await user.type(screen.getByLabelText('Search source lists'), 'ultimate')
    await user.click(screen.getByRole('button', { name: 'Search' }))
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Ultimate Universe/ })).toBeInTheDocument()
    })
    // #3939: the whole path is provenance now, shown only under "Source details".
    expect(screen.queryByText('Marvel/Ultimate.cbl')).not.toBeInTheDocument()
    expect(screen.getByText('JoshCLWren/CBL-ReadingLists · 4 issues')).toBeInTheDocument()
    expect(document.body.textContent).not.toContain('/mnt/bigdata')
  })

  it('shows a reader-friendly title and hides the raw .cbl path (#3939)', async () => {
    const user = userEvent.setup()
    const rawPath =
      'Marvel/Events/CBH/[Marvel] [2024-2026] The New Marvel Ultimate Universe 2.0 (CBH).cbl'
    mockBrowse.mockResolvedValue(
      searchPage('ultimate', [
        {
          ...source,
          name: '[Marvel] [2024-2026] The New Marvel Ultimate Universe 2.0 (CBH)',
          source_path: rawPath,
        },
      ]),
    )
    renderPage()
    await user.type(screen.getByLabelText('Search source lists'), 'ultimate')
    await user.click(screen.getByRole('button', { name: 'Search' }))
    const row = await screen.findByRole('button', {
      name: /The New Marvel Ultimate Universe 2\.0 \(CBH\)/,
    })
    expect(row).toHaveTextContent('The New Marvel Ultimate Universe 2.0 (CBH)')
    expect(row).not.toHaveTextContent(rawPath)
    expect(row).not.toHaveTextContent('.cbl')
    expect(screen.queryByText(rawPath)).not.toBeInTheDocument()
  })

  it('previews under the reader-friendly title and keeps the path in Source details (#3939)', async () => {
    const user = userEvent.setup()
    const rawPath =
      'Marvel/Events/CBH/[Marvel] [2024-2026] The New Marvel Ultimate Universe 2.0 (CBH).cbl'
    const listed: CBLSourceListDiscoveryItem = {
      ...source,
      name: '[Marvel] [2024-2026] The New Marvel Ultimate Universe 2.0 (CBH)',
      source_path: rawPath,
    }
    mockBrowse.mockResolvedValue(searchPage('ultimate', [listed]))
    mockPreview.mockResolvedValue(preview({ source: { source_path: rawPath } }))
    renderPage()
    await user.type(screen.getByLabelText('Search source lists'), 'ultimate')
    await user.click(screen.getByRole('button', { name: 'Search' }))
    await user.click(
      await screen.findByRole('button', { name: /The New Marvel Ultimate Universe 2\.0 \(CBH\)/ }),
    )
    await waitFor(() => {
      expect(
        screen.getByRole('heading', { name: 'The New Marvel Ultimate Universe 2.0 (CBH)' }),
      ).toBeInTheDocument()
    })
    // The path is provenance: it survives only inside the collapsed disclosure.
    const details = screen.getByText('Source details').closest('details')
    expect(details).not.toBeNull()
    expect(details).toContainElement(screen.getByText(rawPath))
  })

  it('shows the add button disabled with a reason while the preview loads (#3939)', async () => {
    const user = userEvent.setup()
    let resolvePreview: (value: CBLAdoptionPreview) => void = () => undefined
    mockPreview.mockImplementation(
      () =>
        new Promise<CBLAdoptionPreview>((resolve) => {
          resolvePreview = resolve
        }),
    )
    renderPage()
    await searchFor(user)
    await user.click(screen.getByRole('button', { name: /Ultimate Universe/ }))

    await waitFor(() => {
      expect(screen.getByText('Wait for the preview to finish.')).toBeInTheDocument()
    })
    const addButton = screen.getByRole('button', { name: 'Add this reading order' })
    expect(addButton).toBeDisabled()
    expect(addButton).toHaveAttribute('aria-disabled', 'true')
    expect(screen.getByRole('status')).toHaveTextContent('Reconciling source…')
    expect(screen.getByRole('button', { name: 'Customize' })).toBeDisabled()

    await act(async () => {
      resolvePreview(preview())
    })
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Add this reading order' })).not.toBeDisabled()
    })
  })

  it('falls back to a generic title when a source declares no readable title or path', async () => {
    const user = userEvent.setup()
    mockBrowse.mockResolvedValue(
      searchPage('ultimate', [
        { ...source, name: '', source_path: '/mnt/bigdata/CBL-ReadingLists' },
      ]),
    )
    mockPreview.mockResolvedValue(preview())
    renderPage()
    await user.type(screen.getByLabelText('Search source lists'), 'ultimate')
    await user.click(screen.getByRole('button', { name: 'Search' }))
    const row = await screen.findByRole('button', { name: /CBL source/ })
    expect(row).toHaveTextContent('CBL source')
    await user.click(row)
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'CBL source' })).toBeInTheDocument()
    })
  })

  it('shows an empty state when no sources match', async () => {
    const user = userEvent.setup()
    mockBrowse.mockResolvedValue(searchPage('nothing', []))
    renderPage()
    await user.type(screen.getByLabelText('Search source lists'), 'nothing')
    await user.click(screen.getByRole('button', { name: 'Search' }))
    await waitFor(() => {
      expect(screen.getByText('No matching source lists found.')).toBeInTheDocument()
    })
  })

  it('shows an error when the catalog cannot be read', async () => {
    const user = userEvent.setup()
    mockBrowse.mockRejectedValue(new Error('Network error'))
    renderPage()
    await user.type(screen.getByLabelText('Search source lists'), 'x')
    await user.click(screen.getByRole('button', { name: 'Search' }))
    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('Network error')
    })
  })

  it('shows root folders and sources immediately on entering the page', async () => {
    mockBrowse.mockResolvedValue(
      browsePage({
        folders: [
          { name: 'DC', path: 'DC', direct_list_count: 0, total_list_count: 3 },
          { name: 'unsorted', path: 'unsorted', direct_list_count: 2, total_list_count: 2 },
        ],
        items: [source],
        total: 1,
        total_pages: 1,
      }),
    )
    renderPage()

    expect(await screen.findByRole('button', { name: /DC/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /unsorted/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Ultimate Universe/ })).toBeInTheDocument()
    expect(screen.getByText('Showing 1–1 of 1 source')).toBeInTheDocument()
    expect(mockBrowse).toHaveBeenCalledWith({ folder: '', query: '', page: 1, pageSize: 50 })
  })

  it('follows nested folder paths including unsorted and keeps breadcrumbs', async () => {
    const user = userEvent.setup()
    mockBrowse.mockImplementation(
      ({ folder }: { folder: string }) => {
        if (folder === 'Marvel/unsorted') {
          return Promise.resolve(
            browsePage({
              folder,
              breadcrumbs: [
                { name: 'All CBLs', path: '' },
                { name: 'Marvel', path: 'Marvel' },
                { name: 'unsorted', path: 'Marvel/unsorted' },
              ],
              items: [source],
              total: 1,
              total_pages: 1,
            }),
          )
        }
        const child =
          folder === 'Marvel'
            ? { name: 'unsorted', path: 'Marvel/unsorted' }
            : { name: 'Marvel', path: 'Marvel' }
        return Promise.resolve(
          browsePage({
            folder,
            breadcrumbs:
              folder === 'Marvel'
                ? [
                    { name: 'All CBLs', path: '' },
                    { name: 'Marvel', path: 'Marvel' },
                  ]
                : [{ name: 'All CBLs', path: '' }],
            folders: [{ ...child, direct_list_count: 0, total_list_count: 1 }],
          }),
        )
      },
    )
    renderPage()

    await user.click(await screen.findByRole('button', { name: /Marvel/ }))
    await waitFor(() => {
      expect(mockBrowse).toHaveBeenLastCalledWith({
        folder: 'Marvel',
        query: '',
        page: 1,
        pageSize: 50,
      })
    })
    expect(screen.getByTestId('location-search')).toHaveTextContent('?folder=Marvel')

    await user.click(await screen.findByRole('button', { name: /unsorted/ }))
    await waitFor(() => {
      expect(mockBrowse).toHaveBeenLastCalledWith({
        folder: 'Marvel/unsorted',
        query: '',
        page: 1,
        pageSize: 50,
      })
    })
    const trail = screen.getByRole('navigation', { name: 'CBL folder path' })
    expect(trail).toHaveTextContent('Marvel')
    expect(trail).toHaveTextContent('unsorted')
    expect(screen.getByRole('button', { name: 'unsorted' })).toHaveAttribute(
      'aria-current',
      'page',
    )

    await user.click(screen.getByRole('button', { name: 'All CBLs' }))
    await waitFor(() => {
      expect(mockBrowse).toHaveBeenLastCalledWith({
        folder: '',
        query: '',
        page: 1,
        pageSize: 50,
      })
    })
  })

  it('paginates beyond 100 sources with stable totals', async () => {
    const user = userEvent.setup()
    const pageItems = (pageNumber: number) =>
      Array.from({ length: pageNumber === 3 ? 37 : 50 }, (_, index) => ({
        ...source,
        id: pageNumber * 1000 + index,
        name: `Catalog Source ${(pageNumber - 1) * 50 + index + 1}`,
      }))
    mockBrowse.mockImplementation(
      ({ page: pageNumber }: { page: number }) =>
        Promise.resolve(
          browsePage({
            page: pageNumber,
            items: pageItems(pageNumber),
            total: 137,
            total_pages: 3,
            has_next: pageNumber < 3,
            has_previous: pageNumber > 1,
          }),
        ),
    )
    renderPage()

    expect(await screen.findByText('Showing 1–50 of 137 sources')).toBeInTheDocument()
    expect(screen.getByText('Page 1 of 3')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Previous page' })).toBeDisabled()

    await user.click(screen.getByRole('button', { name: 'Next page' }))
    await waitFor(() => {
      expect(mockBrowse).toHaveBeenLastCalledWith({
        folder: '',
        query: '',
        page: 2,
        pageSize: 50,
      })
    })
    expect(await screen.findByText('Showing 51–100 of 137 sources')).toBeInTheDocument()
    expect(screen.getByTestId('location-search')).toHaveTextContent('?page=2')

    await user.click(screen.getByRole('button', { name: 'Next page' }))
    expect(await screen.findByText('Showing 101–137 of 137 sources')).toBeInTheDocument()
    expect(screen.getByText('Page 3 of 3')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Next page' })).toBeDisabled()

    await user.click(screen.getByRole('button', { name: 'Previous page' }))
    expect(await screen.findByText('Showing 51–100 of 137 sources')).toBeInTheDocument()
    expect(screen.getByTestId('location-search')).toHaveTextContent('?page=2')
  })

  it('previews a source-only page and returns to the same folder, search, and page', async () => {
    const user = userEvent.setup()
    mockBrowse.mockResolvedValue(
      browsePage({
        scope: 'search',
        query: 'ultimate',
        items: [source],
        total: 1,
        total_pages: 1,
      }),
    )
    mockPreview.mockResolvedValue(preview())
    renderPage('/cbl-sources?folder=Marvel&q=ultimate&page=2')

    await user.click(await screen.findByRole('button', { name: /Ultimate Universe/ }))
    const detail = await screen.findByTestId('cbl-source-detail')
    expect(detail).toHaveTextContent('Ultimate Reading Order')
    expect(detail).toHaveTextContent('4000-1')
    expect(detail).toHaveTextContent('4000-2')
    expect(detail).toHaveTextContent('vol 4000-vol-1')
    expect(screen.getByTestId('location-search')).toHaveTextContent('list=7')

    await user.click(screen.getByRole('link', { name: 'Back to results' }))
    await waitFor(() => {
      expect(screen.queryByTestId('cbl-source-detail')).not.toBeInTheDocument()
    })
    const search = screen.getByTestId('location-search').textContent ?? ''
    expect(search).toContain('folder=Marvel')
    expect(search).toContain('q=ultimate')
    expect(search).toContain('page=2')
    expect(search).not.toContain('list=')
    expect(mockBrowse).toHaveBeenLastCalledWith({
      folder: 'Marvel',
      query: 'ultimate',
      page: 2,
      pageSize: 50,
    })
  })

  it('labels the return link "Back to results" when opening from the catalog root (#4136)', async () => {
    const user = userEvent.setup()
    mockBrowse.mockResolvedValue(
      browsePage({ items: [source], total: 1, total_pages: 1 }),
    )
    mockPreview.mockResolvedValue(preview())
    renderPage()

    await user.click(await screen.findByRole('button', { name: /Ultimate Universe/ }))
    // The detail panel already adds "Back to", so repeated words are a defect.
    expect(await screen.findByRole('link', { name: 'Back to results' })).toBeInTheDocument()
  })

  it('shows the source-only preview without needing owned comics', async () => {
    renderPage('/cbl-sources?list=7')
    const detail = await screen.findByTestId('cbl-source-detail')
    expect(detail).toHaveTextContent('4000-1')
    expect(detail).toHaveTextContent('4000-2')
    // No reader-owned reconciliation is needed to read the shared source.
    expect(mockPreview).not.toHaveBeenCalled()
  })

  it('shows an empty state for an empty folder', async () => {
    mockBrowse.mockResolvedValue(
      browsePage({
        folder: 'Empty',
        breadcrumbs: [
          { name: 'All CBLs', path: '' },
          { name: 'Empty', path: 'Empty' },
        ],
      }),
    )
    renderPage('/cbl-sources?folder=Empty')
    expect(await screen.findByText('No CBL sources in this folder.')).toBeInTheDocument()
  })

  it('shows an empty state for an empty shared catalog', async () => {
    renderPage()
    expect(
      await screen.findByText('No shared CBL sources are available yet.'),
    ).toBeInTheDocument()
  })

  it('explains a missing folder and returns to the catalog root', async () => {
    const user = userEvent.setup()
    const notFound = Object.assign(new Error('Not Found'), {
      isAxiosError: true,
      response: { status: 404, data: { detail: { code: 'folder_not_found', message: 'gone' } } },
    })
    mockBrowse.mockRejectedValueOnce(notFound)
    mockBrowse.mockResolvedValue(
      browsePage({ items: [source], total: 1, total_pages: 1 }),
    )
    renderPage('/cbl-sources?folder=Gone')

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'This folder is no longer in the shared CBL catalog.',
    )
    await user.click(screen.getByRole('button', { name: 'Browse all CBLs' }))
    await waitFor(() => {
      expect(mockBrowse).toHaveBeenLastCalledWith({
        folder: '',
        query: '',
        page: 1,
        pageSize: 50,
      })
    })
    expect(await screen.findByRole('button', { name: /Ultimate Universe/ })).toBeInTheDocument()
    expect(screen.getByTestId('location-search')).not.toHaveTextContent('folder=')
  })

  it('explains an unavailable catalog and retries the same page', async () => {
    const user = userEvent.setup()
    const unavailable = Object.assign(new Error('Service Unavailable'), {
      isAxiosError: true,
      response: { status: 503, data: { detail: { code: 'cbl_catalog_unavailable', message: 'x' } } },
    })
    mockBrowse.mockRejectedValueOnce(unavailable)
    mockBrowse.mockResolvedValue(browsePage({ items: [source], total: 1, total_pages: 1 }))
    renderPage('/cbl-sources?page=2')

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The shared CBL catalog is temporarily unavailable. Try again in a moment.',
    )
    await user.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByRole('button', { name: /Ultimate Universe/ })).toBeInTheDocument()
    expect(mockBrowse).toHaveBeenLastCalledWith({
      folder: '',
      query: '',
      page: 2,
      pageSize: 50,
    })
  })

  it('reports an out-of-range page without losing the matching total', async () => {
    mockBrowse.mockResolvedValue(
      browsePage({
        page: 9,
        total: 137,
        total_pages: 3,
        has_previous: true,
      }),
    )
    renderPage('/cbl-sources?page=9')
    expect(await screen.findByText('No sources on page 9 of 3.')).toBeInTheDocument()
    expect(screen.queryByText(/^Showing /)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Previous page' })).toBeEnabled()
  })

  it('ignores a malformed page parameter and browses the first page', async () => {
    renderPage('/cbl-sources?page=not-a-number')
    await waitFor(() => {
      expect(mockBrowse).toHaveBeenCalledWith({
        folder: '',
        query: '',
        page: 1,
        pageSize: 50,
      })
    })
  })

  it('clears a search and returns to the current folder', async () => {
    const user = userEvent.setup()
    mockBrowse.mockResolvedValue(searchPage('ultimate'))
    renderPage('/cbl-sources?folder=Marvel&q=ultimate')

    await user.click(await screen.findByRole('button', { name: 'Clear search' }))
    await waitFor(() => {
      expect(mockBrowse).toHaveBeenLastCalledWith({
        folder: 'Marvel',
        query: '',
        page: 1,
        pageSize: 50,
      })
    })
    expect(screen.getByLabelText('Search source lists')).toHaveValue('')
    expect(screen.getByTestId('location-search')).not.toHaveTextContent('q=')
  })

})
