import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'

const { confirmIdentitySpy, replaceIdentitySpy, searchSeriesSpy, getSeriesIssuesSpy } = vi.hoisted(() => ({
  confirmIdentitySpy: vi.fn().mockResolvedValue({} as never),
  replaceIdentitySpy: vi.fn().mockResolvedValue({} as never),
  searchSeriesSpy: vi.fn(),
  getSeriesIssuesSpy: vi.fn(),
}))

vi.mock('../services/api', () => ({
  comicVineApi: {
    searchSeries: searchSeriesSpy,
    getSeriesIssues: getSeriesIssuesSpy,
    getIssueIntelligence: vi.fn(),
    getIssueIdentity: vi.fn(),
    confirmIdentity: confirmIdentitySpy,
    replaceIdentity: replaceIdentitySpy,
    refreshMetadata: vi.fn(),
    applyCorrection: vi.fn(),
    listCorrections: vi.fn(),
    revertCorrection: vi.fn(),
  },
}))

vi.mock('../components/Modal', () => ({
  default: ({ isOpen, title, children, size }: { isOpen: boolean; title: string; children: ReactNode; size?: string }) =>
    isOpen ? <div role="dialog" data-modal-size={size}><h2>{title}</h2>{children}</div> : null,
}))

import ComicVineSearchDialog from '../components/ComicVineSearchDialog'

const mockSeries = {
  comicvine_volume_id: 42,
  name: 'Stormwatch',
  publisher: 'WildStorm',
  start_year: 1993,
  issue_count: 12,
  site_detail_url: null,
  image_url: null,
}

const mockIssue = {
  comicvine_issue_id: 36956,
  issue_number: '1',
  name: 'The Dark Side',
  cover_date: '1993-01-01',
  store_date: null,
  image_url: null,
  site_detail_url: null,
}

const defaultProps = (overrides = {}) => ({
  isOpen: true,
  issueId: 43,
  threadTitle: 'Stormwatch Vol. 1',
  issueNumber: '1',
  mode: 'confirm' as 'confirm' | 'replace',
  onClose: vi.fn(),
  onConfirmed: vi.fn(),
  ...overrides,
})

describe('ComicVineSearchDialog mode branching', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    searchSeriesSpy.mockResolvedValue({ query: '', results: [mockSeries], total_available: 1 })
    getSeriesIssuesSpy.mockResolvedValue({ comicvine_volume_id: 42, series_name: 'Stormwatch', issues: [mockIssue] })
  })

  it('calls confirmIdentity in confirm mode when the user confirms a selection', async () => {
    render(<ComicVineSearchDialog {...defaultProps()} />)

    const input = screen.getByPlaceholderText('Search series title...')
    fireEvent.change(input, { target: { value: 'Stormwatch' } })
    await waitFor(() => expect(screen.getByText('Stormwatch')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Stormwatch'))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Confirm Identity' })).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: 'Confirm Identity' }))

    await waitFor(() => expect(confirmIdentitySpy).toHaveBeenCalledWith(43, 36956))
    expect(replaceIdentitySpy).not.toHaveBeenCalled()
  })

  it('calls replaceIdentity in replace mode when the user confirms a selection', async () => {
    render(<ComicVineSearchDialog {...defaultProps({ mode: 'replace' })} />)

    const input = screen.getByPlaceholderText('Search series title...')
    fireEvent.change(input, { target: { value: 'Stormwatch' } })
    await waitFor(() => expect(screen.getByText('Stormwatch')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Stormwatch'))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Confirm Identity' })).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: 'Confirm Identity' }))

    await waitFor(() => expect(replaceIdentitySpy).toHaveBeenCalledWith(43, 36956))
    expect(confirmIdentitySpy).not.toHaveBeenCalled()
  })

  it('renders same-title series results as distinguishable options', async () => {
    searchSeriesSpy.mockResolvedValue({
      query: 'Ultimate Spider-Man',
      results: [
        {
          comicvine_volume_id: 471,
          name: 'Ultimate Spider-Man',
          publisher: 'Marvel',
          start_year: 2000,
          issue_count: 160,
          site_detail_url: null,
          image_url: null,
        },
        {
          comicvine_volume_id: 114402,
          name: 'Ultimate Spider-Man',
          publisher: 'Marvel',
          start_year: 2024,
          issue_count: 18,
          site_detail_url: null,
          image_url: null,
        },
      ],
      total_available: 2,
    })
    render(<ComicVineSearchDialog {...defaultProps({ threadTitle: 'Ultimate Spider-Man' })} />)

    const input = screen.getByPlaceholderText('Search series title...')
    fireEvent.change(input, { target: { value: '' } })
    fireEvent.change(input, { target: { value: 'Ultimate Spider-Man' } })

    const options = await screen.findAllByRole('button', { name: /Ultimate Spider-Man/ })
    expect(options).toHaveLength(2)

    const [firstLabel, secondLabel] = options.map((option) => option.getAttribute('aria-label'))
    expect(firstLabel).not.toEqual(secondLabel)
    expect(firstLabel).toMatch(/2000/)
    expect(secondLabel).toMatch(/2024/)

    expect(options[0].textContent).toMatch(/2000/)
    expect(options[0].textContent).toMatch(/160 issues/)
    expect(options[1].textContent).toMatch(/2024/)
    expect(options[1].textContent).toMatch(/18 issues/)

    expect(screen.queryByText(/471/)).not.toBeInTheDocument()
    expect(screen.queryByText(/114402/)).not.toBeInTheDocument()
  })

  it('keeps the exact provider identity when a same-title result is selected', async () => {
    const ultimate = {
      comicvine_volume_id: 471,
      name: 'Ultimate Spider-Man',
      publisher: 'Marvel',
      start_year: 2000,
      issue_count: 160,
      site_detail_url: null,
      image_url: null,
    }
    const ultimate2024 = { ...ultimate, comicvine_volume_id: 114402, start_year: 2024 }
    searchSeriesSpy.mockResolvedValue({
      query: 'Ultimate Spider-Man',
      results: [ultimate, ultimate2024],
      total_available: 2,
    })
    render(<ComicVineSearchDialog {...defaultProps({ threadTitle: 'Ultimate Spider-Man' })} />)

    const input = screen.getByPlaceholderText('Search series title...')
    fireEvent.change(input, { target: { value: '' } })
    fireEvent.change(input, { target: { value: 'Ultimate Spider-Man' } })

    const options = await screen.findAllByRole('button', { name: /Ultimate Spider-Man/ })
    fireEvent.click(options[1])

    await waitFor(() =>
      expect(getSeriesIssuesSpy).toHaveBeenCalledWith(114402, 'Ultimate Spider-Man'),
    )
  })
})

describe('ComicVineSearchDialog issue #1695 fixes', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    searchSeriesSpy.mockResolvedValue({ query: '', results: [mockSeries], total_available: 1 })
    getSeriesIssuesSpy.mockResolvedValue({ comicvine_volume_id: 42, series_name: 'Stormwatch', issues: [mockIssue] })
  })

  it('auto-searches when dialog opens with a pre-filled threadTitle', async () => {
    render(<ComicVineSearchDialog {...defaultProps({ threadTitle: 'Stormwatch Vol. 1' })} />)

    await waitFor(() =>
      expect(searchSeriesSpy).toHaveBeenCalledWith('Stormwatch Vol. 1', 10),
    )
  })

  it('does not show "No series found" before any search is performed', async () => {
    searchSeriesSpy.mockResolvedValue({ query: '', results: [], total_available: 0 })

    render(<ComicVineSearchDialog {...defaultProps({ threadTitle: '' })} />)

    expect(screen.queryByText('No series found. Try a different search term.')).not.toBeInTheDocument()
    expect(screen.getByText('Type a series name to search ComicVine')).toBeInTheDocument()
  })

  it('shows "No series found" only after a search returns empty', async () => {
    searchSeriesSpy.mockResolvedValue({ query: 'Nonexistent', results: [], total_available: 0 })

    render(<ComicVineSearchDialog {...defaultProps({ threadTitle: '' })} />)

    const input = screen.getByPlaceholderText('Search series title...')
    fireEvent.change(input, { target: { value: 'Nonexistent' } })

    await waitFor(() =>
      expect(screen.getByText('No series found. Try a different search term.')).toBeInTheDocument(),
    )
  })

  it('shows error message when search fails', async () => {
    searchSeriesSpy.mockRejectedValue(new Error('Network error'))

    render(<ComicVineSearchDialog {...defaultProps({ threadTitle: '' })} />)

    const input = screen.getByPlaceholderText('Search series title...')
    fireEvent.change(input, { target: { value: 'Stormwatch' } })

    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent('Failed to search ComicVine. Please try again.'),
    )
  })

  it('does not show "No series found" when an error is displayed', async () => {
    searchSeriesSpy.mockRejectedValue(new Error('Network error'))

    render(<ComicVineSearchDialog {...defaultProps({ threadTitle: '' })} />)

    const input = screen.getByPlaceholderText('Search series title...')
    fireEvent.change(input, { target: { value: 'Stormwatch' } })

    await waitFor(() =>
      expect(screen.getByRole('alert')).toBeInTheDocument(),
    )
    expect(screen.queryByText('No series found. Try a different search term.')).not.toBeInTheDocument()
  })

  it('shows neutral hint when query is cleared', async () => {
    render(<ComicVineSearchDialog {...defaultProps({ threadTitle: 'Stormwatch' })} />)

    await waitFor(() => {
      expect(searchSeriesSpy).toHaveBeenCalled()
    })

    const input = screen.getByPlaceholderText('Search series title...')
    fireEvent.change(input, { target: { value: '' } })

    await waitFor(() => {
      expect(screen.getByText('Type a series name to search ComicVine')).toBeInTheDocument()
    })
    expect(screen.queryByText('No series found. Try a different search term.')).not.toBeInTheDocument()
  })

  it('opens a large modal on desktop', async () => {
    render(<ComicVineSearchDialog {...defaultProps()} />)

    await waitFor(() => {
      expect(screen.getByRole('dialog')).toHaveAttribute('data-modal-size', 'large')
    })
  })

  it('renders series metadata at readable size with high contrast', async () => {
    render(<ComicVineSearchDialog {...defaultProps()} />)

    await waitFor(() => {
      expect(screen.getByText('Stormwatch')).toBeInTheDocument()
    })

    const metadataElements = screen.getAllByText(/WildStorm · 1993 · 12 issues/)
    expect(metadataElements.length).toBeGreaterThan(0)
    metadataElements.forEach((el) => {
      expect(el.className).toMatch(/text-sm/)
      expect(el.className).toMatch(/text-stone-300/)
    })
  })

  it('skips auto-map when issueNumber is null and shows plain issue list', async () => {
    getSeriesIssuesSpy.mockResolvedValue({
      comicvine_volume_id: 42,
      series_name: 'Stormwatch',
      issues: [mockIssue],
    })
    render(<ComicVineSearchDialog {...defaultProps({ issueNumber: null })} />)

    const input = screen.getByPlaceholderText('Search series title...')
    fireEvent.change(input, { target: { value: 'Stormwatch' } })
    await waitFor(() => expect(screen.getByText('Stormwatch')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Stormwatch'))

    await waitFor(() => expect(screen.getByText('#1')).toBeInTheDocument())
    expect(screen.queryByTestId('rematch-issue-context')).not.toBeInTheDocument()
    expect(screen.queryByText('Confirm Identity')).not.toBeInTheDocument()
  })

  it('shows "No issues found" when issueNumber is null and results are empty', async () => {
    getSeriesIssuesSpy.mockResolvedValue({
      comicvine_volume_id: 42,
      series_name: 'Stormwatch',
      issues: [],
    })
    render(<ComicVineSearchDialog {...defaultProps({ issueNumber: null })} />)

    const input = screen.getByPlaceholderText('Search series title...')
    fireEvent.change(input, { target: { value: 'Stormwatch' } })
    await waitFor(() => expect(screen.getByText('Stormwatch')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Stormwatch'))

    await waitFor(() =>
      expect(screen.getByText('No issues found in this series.')).toBeInTheDocument(),
    )
  })

  it('shows no-match message when issueNumber is provided but the series has no issues', async () => {
    getSeriesIssuesSpy.mockResolvedValue({
      comicvine_volume_id: 42,
      series_name: 'Stormwatch',
      issues: [],
    })
    render(<ComicVineSearchDialog {...defaultProps({ issueNumber: '99' })} />)

    const input = screen.getByPlaceholderText('Search series title...')
    fireEvent.change(input, { target: { value: 'Stormwatch' } })
    await waitFor(() => expect(screen.getByText('Stormwatch')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Stormwatch'))

    await waitFor(() =>
      expect(screen.getByText('No match for #99 in this series.')).toBeInTheDocument(),
    )
  })

  it('shows error when loading series issues fails', async () => {
    getSeriesIssuesSpy.mockRejectedValue(new Error('Network error'))
    render(<ComicVineSearchDialog {...defaultProps()} />)

    const input = screen.getByPlaceholderText('Search series title...')
    fireEvent.change(input, { target: { value: 'Stormwatch' } })
    await waitFor(() => expect(screen.getByText('Stormwatch')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Stormwatch'))

    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent('Failed to load issues. Please try again.'),
    )
  })

  it('renders series name and metadata without truncating the year', async () => {
    searchSeriesSpy.mockResolvedValue({
      query: 'Test',
      results: [{
        ...mockSeries,
        name: 'A Very Long Series Name That Could Potentially Be Truncated',
      }],
      total_available: 1,
    })

    render(<ComicVineSearchDialog {...defaultProps({ threadTitle: 'A Very Long Series Name That Could Potentially Be Truncated' })} />)

    await waitFor(() => {
      expect(screen.getByText(/A Very Long Series Name/)).toBeInTheDocument()
    })

    const metaText = screen.getByText(/WildStorm · 1993 · 12 issues/)
    expect(metaText).toBeInTheDocument()
  })

})