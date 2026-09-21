import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'

const { confirmIdentitySpy, replaceIdentitySpy, searchSeriesSpy, getSeriesIssuesSpy, resolveIdentitySpy } = vi.hoisted(() => ({
  confirmIdentitySpy: vi.fn().mockResolvedValue({} as never),
  replaceIdentitySpy: vi.fn().mockResolvedValue({} as never),
  searchSeriesSpy: vi.fn(),
  getSeriesIssuesSpy: vi.fn(),
  resolveIdentitySpy: vi.fn(),
}))

vi.mock('../services/api', () => ({
  comicVineApi: {
    searchSeries: searchSeriesSpy,
    getSeriesIssues: getSeriesIssuesSpy,
    resolveIdentity: resolveIdentitySpy,
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
    searchSeriesSpy.mockResolvedValue({ query: '', results: [mockSeries], total_available: 1, offset: 0, limit: 10, has_more: false, next_offset: null })
    getSeriesIssuesSpy.mockResolvedValue({ comicvine_volume_id: 42, series_name: 'Stormwatch', issues: [mockIssue] })
  })

  it('calls confirmIdentity in confirm mode when the user confirms a selection', async () => {
    render(<ComicVineSearchDialog {...defaultProps()} />)

    const input = screen.getByPlaceholderText('Search series title or paste a ComicVine URL')
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

    const input = screen.getByPlaceholderText('Search series title or paste a ComicVine URL')
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

    const input = screen.getByPlaceholderText('Search series title or paste a ComicVine URL')
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

    const input = screen.getByPlaceholderText('Search series title or paste a ComicVine URL')
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
    searchSeriesSpy.mockResolvedValue({ query: '', results: [mockSeries], total_available: 1, offset: 0, limit: 10, has_more: false, next_offset: null })
    getSeriesIssuesSpy.mockResolvedValue({ comicvine_volume_id: 42, series_name: 'Stormwatch', issues: [mockIssue] })
  })

  it('auto-searches when dialog opens with a pre-filled threadTitle', async () => {
    render(<ComicVineSearchDialog {...defaultProps({ threadTitle: 'Stormwatch Vol. 1' })} />)

    await waitFor(() =>
      expect(searchSeriesSpy).toHaveBeenCalledWith('Stormwatch Vol. 1', 10, 0),
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

    const input = screen.getByPlaceholderText('Search series title or paste a ComicVine URL')
    fireEvent.change(input, { target: { value: 'Nonexistent' } })

    await waitFor(() =>
      expect(screen.getByText('No series found. Try a different search term.')).toBeInTheDocument(),
    )
  })

  it('shows error message when search fails', async () => {
    searchSeriesSpy.mockRejectedValue(new Error('Network error'))

    render(<ComicVineSearchDialog {...defaultProps({ threadTitle: '' })} />)

    const input = screen.getByPlaceholderText('Search series title or paste a ComicVine URL')
    fireEvent.change(input, { target: { value: 'Stormwatch' } })

    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent('Failed to search ComicVine. Please try again.'),
    )
  })

  it('does not show "No series found" when an error is displayed', async () => {
    searchSeriesSpy.mockRejectedValue(new Error('Network error'))

    render(<ComicVineSearchDialog {...defaultProps({ threadTitle: '' })} />)

    const input = screen.getByPlaceholderText('Search series title or paste a ComicVine URL')
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

    const input = screen.getByPlaceholderText('Search series title or paste a ComicVine URL')
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

    const input = screen.getByPlaceholderText('Search series title or paste a ComicVine URL')
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

    const input = screen.getByPlaceholderText('Search series title or paste a ComicVine URL')
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

    const input = screen.getByPlaceholderText('Search series title or paste a ComicVine URL')
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

    const input = screen.getByPlaceholderText('Search series title or paste a ComicVine URL')
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
      offset: 0,
      limit: 10,
      has_more: false,
      next_offset: null,
    })

    render(<ComicVineSearchDialog {...defaultProps({ threadTitle: 'A Very Long Series Name That Could Potentially Be Truncated' })} />)

    await waitFor(() => {
      expect(screen.getByText(/A Very Long Series Name/)).toBeInTheDocument()
    })

    const metaText = screen.getByText(/WildStorm · 1993 · 12 issues/)
    expect(metaText).toBeInTheDocument()
  })

})

const ISSUE_URL = 'https://comicvine.gamespot.com/superman-34-i-superman/4000-1154070/'

const mockResolvedIssue = {
  comicvine_issue_id: 1154070,
  series_name: 'Superman',
  volume_id: 148476,
  issue_number: '34',
  name: 'I, Superman',
  cover_date: '2023-09-01',
  store_date: null,
  image_url: null,
  site_detail_url: null,
}

const mockVolume = {
  comicvine_volume_id: 148476,
  name: 'Superman',
  publisher: 'DC Comics',
  start_year: 2023,
  issue_count: 22,
  site_detail_url: null,
  image_url: null,
}

describe('ComicVineSearchDialog direct URL resolution (#2803)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    searchSeriesSpy.mockResolvedValue({ query: '', results: [], total_available: 0, offset: 0, limit: 10, has_more: false, next_offset: null })
    getSeriesIssuesSpy.mockResolvedValue({ comicvine_volume_id: 42, series_name: 'Stormwatch', issues: [mockIssue] })
    resolveIdentitySpy.mockReset()
  })

  it('resolves an issue URL to the confirm step without searching the volume', async () => {
    resolveIdentitySpy.mockResolvedValue({ input: ISSUE_URL, kind: 'issue', validation_error: null, issue: mockResolvedIssue, volume: null, issues: [] })

    render(<ComicVineSearchDialog {...defaultProps({ issueNumber: '34' })} />)

    // The dialog auto-searches the pre-filled threadTitle on open; isolate the
    // URL-paste behavior so the assertion below only covers post-paste calls.
    await waitFor(() => expect(searchSeriesSpy).toHaveBeenCalled())
    searchSeriesSpy.mockClear()

    const input = screen.getByPlaceholderText('Search series title or paste a ComicVine URL')
    fireEvent.change(input, { target: { value: ISSUE_URL } })

    await waitFor(() =>
      expect(resolveIdentitySpy).toHaveBeenCalledWith(ISSUE_URL),
    )
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Confirm Identity' })).toBeInTheDocument(),
    )
    expect(screen.getByText('Superman')).toBeInTheDocument()
    expect(screen.getByText(/I, Superman/)).toBeInTheDocument()
    expect(screen.getByText('2023-09-01')).toBeInTheDocument()
    expect(searchSeriesSpy).not.toHaveBeenCalled()
    expect(getSeriesIssuesSpy).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: 'Confirm Identity' }))

    await waitFor(() => expect(confirmIdentitySpy).toHaveBeenCalledWith(43, 1154070))
    expect(replaceIdentitySpy).not.toHaveBeenCalled()
  })

  it('resolves an issue URL through the replace endpoint in replace mode', async () => {
    resolveIdentitySpy.mockResolvedValue({ input: ISSUE_URL, kind: 'issue', validation_error: null, issue: mockResolvedIssue, volume: null, issues: [] })

    render(<ComicVineSearchDialog {...defaultProps({ mode: 'replace', issueNumber: '34' })} />)

    const input = screen.getByPlaceholderText('Search series title or paste a ComicVine URL')
    fireEvent.change(input, { target: { value: ISSUE_URL } })

    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Confirm Identity' })).toBeInTheDocument(),
    )

    fireEvent.click(screen.getByRole('button', { name: 'Confirm Identity' }))

    await waitFor(() => expect(replaceIdentitySpy).toHaveBeenCalledWith(43, 1154070))
    expect(confirmIdentitySpy).not.toHaveBeenCalled()
  })

  it('resolves a volume URL and auto-selects the exact issue-number match', async () => {
    const mockIssue34 = { ...mockIssue, comicvine_issue_id: 1002, issue_number: '34', name: 'I, Superman' }
    resolveIdentitySpy.mockResolvedValue({
      input: 'https://comicvine.gamespot.com/superman/4050-148476/',
      kind: 'volume',
      validation_error: null,
      issue: null,
      volume: mockVolume,
      issues: [mockIssue, mockIssue34],
    })

    render(<ComicVineSearchDialog {...defaultProps({ issueNumber: '34' })} />)

    const input = screen.getByPlaceholderText('Search series title or paste a ComicVine URL')
    fireEvent.change(input, { target: { value: 'https://comicvine.gamespot.com/superman/4050-148476/' } })

    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Confirm Identity' })).toBeInTheDocument(),
    )
    expect(screen.getByText(/I, Superman/)).toBeInTheDocument()
    expect(getSeriesIssuesSpy).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: 'Confirm Identity' }))

    await waitFor(() => expect(confirmIdentitySpy).toHaveBeenCalledWith(43, 1002))
  })

  it('shows the issue list when a volume URL has no exact issue-number match', async () => {
    resolveIdentitySpy.mockResolvedValue({
      input: 'https://comicvine.gamespot.com/superman/4050-148476/',
      kind: 'volume',
      validation_error: null,
      issue: null,
      volume: mockVolume,
      issues: [mockIssue],
    })

    render(<ComicVineSearchDialog {...defaultProps({ issueNumber: '99' })} />)

    const input = screen.getByPlaceholderText('Search series title or paste a ComicVine URL')
    fireEvent.change(input, { target: { value: 'https://comicvine.gamespot.com/superman/4050-148476/' } })

    await waitFor(() => expect(screen.getByText('#1')).toBeInTheDocument())
    expect(screen.getByTestId('rematch-issue-context')).toHaveTextContent('#99')
    expect(screen.queryByRole('button', { name: 'Confirm Identity' })).not.toBeInTheDocument()
  })

  it('shows a clear inline validation error for an unsupported URL without mutating identity', async () => {
    resolveIdentitySpy.mockResolvedValue({
      input: 'https://comicvine.example.com/superman/4050-148476/',
      kind: 'search',
      validation_error: "That doesn't look like a ComicVine issue or volume URL.",
      issue: null,
      volume: null,
      issues: [],
    })

    render(<ComicVineSearchDialog {...defaultProps()} />)

    const input = screen.getByPlaceholderText('Search series title or paste a ComicVine URL')
    fireEvent.change(input, { target: { value: 'https://comicvine.example.com/superman/4050-148476/' } })

    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent("That doesn't look like a ComicVine issue or volume URL."),
    )
    expect(screen.getByPlaceholderText('Search series title or paste a ComicVine URL')).toBeInTheDocument()
    expect(confirmIdentitySpy).not.toHaveBeenCalled()
  })

  it('keeps the dialog usable when URL resolution fails at the provider', async () => {
    resolveIdentitySpy.mockRejectedValue(new Error('Network error'))

    render(<ComicVineSearchDialog {...defaultProps()} />)

    const input = screen.getByPlaceholderText('Search series title or paste a ComicVine URL')
    fireEvent.change(input, { target: { value: ISSUE_URL } })

    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent('Failed to search ComicVine. Please try again.'),
    )
    expect(screen.getByPlaceholderText('Search series title or paste a ComicVine URL')).toBeInTheDocument()
    expect(confirmIdentitySpy).not.toHaveBeenCalled()
  })

  it('handles volume resolution with empty issues array', async () => {
    resolveIdentitySpy.mockResolvedValue({
      input: 'https://comicvine.gamespot.com/superman/4050-148476/',
      kind: 'volume',
      validation_error: null,
      issue: null,
      volume: mockVolume,
      issues: [],
    })

    render(<ComicVineSearchDialog {...defaultProps({ issueNumber: '34' })} />)

    const input = screen.getByPlaceholderText('Search series title or paste a ComicVine URL')
    fireEvent.change(input, { target: { value: 'https://comicvine.gamespot.com/superman/4050-148476/' } })

    await waitFor(() => expect(screen.getByText('#34')).toBeInTheDocument())
    expect(screen.getByTestId('rematch-issue-context')).toHaveTextContent('#34')
    expect(screen.queryByRole('button', { name: 'Confirm Identity' })).not.toBeInTheDocument()
  })

  it('handles volume resolution with null issue data', async () => {
    resolveIdentitySpy.mockResolvedValue({
      input: 'https://comicvine.gamespot.com/superman-34-i-superman/4000-1154070/',
      kind: 'issue',
      validation_error: null,
      issue: null,
      volume: null,
      issues: [],
    })

    render(<ComicVineSearchDialog {...defaultProps()} />)

    const input = screen.getByPlaceholderText('Search series title or paste a ComicVine URL')
    fireEvent.change(input, { target: { value: 'https://comicvine.gamespot.com/superman-34-i-superman/4000-1154070/' } })

    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent('Failed to resolve ComicVine issue. Please try again.'),
    )
    expect(screen.getByPlaceholderText('Search series title or paste a ComicVine URL')).toBeInTheDocument()
    expect(confirmIdentitySpy).not.toHaveBeenCalled()
  })

  it('handles search kind resolution (plain text)', async () => {
    resolveIdentitySpy.mockResolvedValue({
      input: 'Just some plain text',
      kind: 'search',
      validation_error: null,
      issue: null,
      volume: null,
      issues: [],
    })

    render(<ComicVineSearchDialog {...defaultProps()} />)

    const input = screen.getByPlaceholderText('Search series title or paste a ComicVine URL')
    fireEvent.change(input, { target: { value: 'Just some plain text' } })

    await waitFor(() => {
      expect(searchSeriesSpy).toHaveBeenCalledWith('Just some plain text', 10, 0)
    })
    expect(screen.getByPlaceholderText('Search series title or paste a ComicVine URL')).toBeInTheDocument()
    expect(confirmIdentitySpy).not.toHaveBeenCalled()
  })
})

describe('ComicVineSearchDialog paginated series search (#2803)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    searchSeriesSpy.mockReset()
    getSeriesIssuesSpy.mockResolvedValue({ comicvine_volume_id: 42, series_name: 'Stormwatch', issues: [mockIssue] })
    resolveIdentitySpy.mockReset()
  })

  it('shows Load more when more results exist, appends them without duplicates, and resets on query change', async () => {
    const pageOne = {
      query: 'Super',
      results: [
        { ...mockSeries, comicvine_volume_id: 1, name: 'Super Series' },
        { ...mockSeries, comicvine_volume_id: 2, name: 'Super Annual' },
      ],
      total_available: 3,
      offset: 0,
      limit: 10,
      has_more: true,
      next_offset: 2,
    }
    const pageTwo = {
      query: 'Super',
      results: [
        { ...mockSeries, comicvine_volume_id: 2, name: 'Super Annual' },
        { ...mockSeries, comicvine_volume_id: 3, name: 'Super Special' },
      ],
      total_available: 3,
      offset: 2,
      limit: 10,
      has_more: false,
      next_offset: null,
    }
    searchSeriesSpy
      .mockResolvedValueOnce(pageOne)
      .mockResolvedValueOnce(pageTwo)
      .mockResolvedValueOnce({
        query: 'X-Force',
        results: [{ ...mockSeries, comicvine_volume_id: 9, name: 'X-Force' }],
        total_available: 1,
        offset: 0,
        limit: 10,
        has_more: false,
        next_offset: null,
      })

    render(<ComicVineSearchDialog {...defaultProps({ threadTitle: '' })} />)

    const input = screen.getByPlaceholderText('Search series title or paste a ComicVine URL')
    fireEvent.change(input, { target: { value: 'Super' } })

    await waitFor(() => expect(screen.getByText('Super Series')).toBeInTheDocument())
    expect(screen.getByTestId('comicvine-load-more')).toBeInTheDocument()

    fireEvent.click(screen.getByTestId('comicvine-load-more'))

    await waitFor(() => expect(screen.getByText('Super Special')).toBeInTheDocument())
    expect(searchSeriesSpy).toHaveBeenLastCalledWith('Super', 10, 2)

    const superAnnualButtons = screen.getAllByText('Super Annual')
    expect(superAnnualButtons).toHaveLength(1)
    expect(screen.getByText('Super Series')).toBeInTheDocument()
    expect(screen.queryByTestId('comicvine-load-more')).not.toBeInTheDocument()

    fireEvent.change(input, { target: { value: 'X-Force' } })

    await waitFor(() => expect(screen.getByText('X-Force')).toBeInTheDocument())
    expect(searchSeriesSpy).toHaveBeenLastCalledWith('X-Force', 10, 0)
    expect(screen.queryByText('Super Series')).not.toBeInTheDocument()
    expect(screen.queryByText('Super Special')).not.toBeInTheDocument()
  })

  it('does not request the next page when the search is already running', async () => {
    const pageOne = {
      query: 'Super',
      results: [{ ...mockSeries, comicvine_volume_id: 1, name: 'Super Series' }],
      total_available: 20,
      offset: 0,
      limit: 10,
      has_more: true,
      next_offset: 1,
    }
    searchSeriesSpy.mockResolvedValue(pageOne)

    render(<ComicVineSearchDialog {...defaultProps({ threadTitle: '' })} />)

    const input = screen.getByPlaceholderText('Search series title or paste a ComicVine URL')
    fireEvent.change(input, { target: { value: 'Super' } })

    await waitFor(() => expect(screen.getByText('Super Series')).toBeInTheDocument())
    const loadMore = screen.getByTestId('comicvine-load-more')
    fireEvent.click(loadMore)
    fireEvent.click(loadMore)

    await waitFor(() =>
      expect(searchSeriesSpy).toHaveBeenCalledTimes(2),
    )
  })

  it('does not show Load more when has_more is false', async () => {
    searchSeriesSpy.mockResolvedValue({
      query: 'Super',
      results: [{ ...mockSeries, comicvine_volume_id: 1, name: 'Super Series' }],
      total_available: 1,
      offset: 0,
      limit: 10,
      has_more: false,
      next_offset: null,
    })

    render(<ComicVineSearchDialog {...defaultProps({ threadTitle: '' })} />)

    const input = screen.getByPlaceholderText('Search series title or paste a ComicVine URL')
    fireEvent.change(input, { target: { value: 'Super' } })

    await waitFor(() => expect(screen.getByText('Super Series')).toBeInTheDocument())
    expect(screen.queryByTestId('comicvine-load-more')).not.toBeInTheDocument()
  })

  it('does not show Load more when nextOffset is null', async () => {
    searchSeriesSpy.mockResolvedValue({
      query: 'Super',
      results: [{ ...mockSeries, comicvine_volume_id: 1, name: 'Super Series' }],
      total_available: 2,
      offset: 0,
      limit: 10,
      has_more: true,
      next_offset: null,
    })

    render(<ComicVineSearchDialog {...defaultProps({ threadTitle: '' })} />)

    const input = screen.getByPlaceholderText('Search series title or paste a ComicVine URL')
    fireEvent.change(input, { target: { value: 'Super' } })

    await waitFor(() => expect(screen.getByText('Super Series')).toBeInTheDocument())
    expect(screen.queryByTestId('comicvine-load-more')).not.toBeInTheDocument()
  })
})

describe('ComicVineSearchDialog branch coverage gaps', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    searchSeriesSpy.mockResolvedValue({ query: '', results: [mockSeries], total_available: 1, offset: 0, limit: 10, has_more: false, next_offset: null })
    getSeriesIssuesSpy.mockResolvedValue({ comicvine_volume_id: 42, series_name: 'Stormwatch', issues: [mockIssue] })
    resolveIdentitySpy.mockReset()
  })

  it('navigates back from confirm to select-issue when not a direct issue resolution', async () => {
    render(<ComicVineSearchDialog {...defaultProps({ issueNumber: null })} />)

    const input = screen.getByPlaceholderText('Search series title or paste a ComicVine URL')
    fireEvent.change(input, { target: { value: 'Stormwatch' } })
    await waitFor(() => expect(screen.getByText('Stormwatch')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Stormwatch'))
    await waitFor(() => expect(screen.getByText('#1')).toBeInTheDocument())
    fireEvent.click(screen.getByText('#1'))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Confirm Identity' })).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: '← Back to issues' }))
    await waitFor(() => expect(screen.getByText('← Back to search')).toBeInTheDocument())
  })

  it('navigates back from confirm to search when resolved via direct issue URL', async () => {
    resolveIdentitySpy.mockResolvedValue({ input: ISSUE_URL, kind: 'issue', validation_error: null, issue: mockResolvedIssue, volume: null, issues: [] })

    render(<ComicVineSearchDialog {...defaultProps({ issueNumber: '34' })} />)

    await waitFor(() => expect(searchSeriesSpy).toHaveBeenCalled())
    searchSeriesSpy.mockClear()

    const input = screen.getByPlaceholderText('Search series title or paste a ComicVine URL')
    fireEvent.change(input, { target: { value: ISSUE_URL } })

    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Confirm Identity' })).toBeInTheDocument(),
    )

    fireEvent.click(screen.getByRole('button', { name: '← Back to search' }))
    expect(screen.getByPlaceholderText('Search series title or paste a ComicVine URL')).toBeInTheDocument()
  })

  it('skips confirm when issueId is null', async () => {
    resolveIdentitySpy.mockResolvedValue({ input: ISSUE_URL, kind: 'issue', validation_error: null, issue: mockResolvedIssue, volume: null, issues: [] })

    render(<ComicVineSearchDialog {...defaultProps({ issueId: null, issueNumber: '34' })} />)

    await waitFor(() => expect(searchSeriesSpy).toHaveBeenCalled())
    searchSeriesSpy.mockClear()

    const input = screen.getByPlaceholderText('Search series title or paste a ComicVine URL')
    fireEvent.change(input, { target: { value: ISSUE_URL } })

    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Confirm Identity' })).toBeInTheDocument(),
    )

    fireEvent.click(screen.getByRole('button', { name: 'Confirm Identity' }))
    await waitFor(() => {
      expect(confirmIdentitySpy).not.toHaveBeenCalled()
      expect(replaceIdentitySpy).not.toHaveBeenCalled()
    })
  })

  it('handles Enter key to trigger search', async () => {
    render(<ComicVineSearchDialog {...defaultProps({ threadTitle: '' })} />)

    const input = screen.getByPlaceholderText('Search series title or paste a ComicVine URL')
    fireEvent.change(input, { target: { value: 'X-Men' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    await waitFor(() => expect(searchSeriesSpy).toHaveBeenCalledWith('X-Men', 10, 0))
  })

  it('renders series results with image_url', async () => {
    searchSeriesSpy.mockResolvedValue({
      query: 'Storm',
      results: [{ ...mockSeries, image_url: 'https://example.com/series.jpg' }],
      total_available: 1,
      offset: 0,
      limit: 10,
      has_more: false,
      next_offset: null,
    })

    const { container } = render(<ComicVineSearchDialog {...defaultProps({ threadTitle: '' })} />)

    const input = screen.getByPlaceholderText('Search series title or paste a ComicVine URL')
    fireEvent.change(input, { target: { value: 'Storm' } })

    await waitFor(() => expect(screen.getByText('Stormwatch')).toBeInTheDocument())
    const images = container.querySelectorAll('img')
    expect(images.length).toBeGreaterThanOrEqual(1)
  })

  it('renders issue candidates with image_url', async () => {
    getSeriesIssuesSpy.mockResolvedValue({
      comicvine_volume_id: 42,
      series_name: 'Stormwatch',
      issues: [{ ...mockIssue, image_url: 'https://example.com/issue.jpg' }],
    })

    render(<ComicVineSearchDialog {...defaultProps({ issueNumber: null })} />)

    const input = screen.getByPlaceholderText('Search series title or paste a ComicVine URL')
    fireEvent.change(input, { target: { value: 'Stormwatch' } })
    await waitFor(() => expect(screen.getByText('Stormwatch')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Stormwatch'))
    await waitFor(() => expect(screen.getByText('#1')).toBeInTheDocument())
    const container = screen.getByRole('dialog')
    const images = container.querySelectorAll('img')
    expect(images.length).toBeGreaterThanOrEqual(1)
  })

  it('renders confirm card with image_url from direct issue', async () => {
    resolveIdentitySpy.mockResolvedValue({
      input: ISSUE_URL,
      kind: 'issue',
      validation_error: null,
      issue: { ...mockResolvedIssue, image_url: 'https://example.com/confirm.jpg' },
      volume: null,
      issues: [],
    })

    const { container } = render(<ComicVineSearchDialog {...defaultProps({ issueNumber: '34' })} />)

    const input = screen.getByPlaceholderText('Search series title or paste a ComicVine URL')
    fireEvent.change(input, { target: { value: ISSUE_URL } })

    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Confirm Identity' })).toBeInTheDocument(),
    )
    const images = container.querySelectorAll('img')
    expect(images.length).toBeGreaterThanOrEqual(1)
  })

  it('shows no issues message when issueNumber is null and issue list is empty', async () => {
    getSeriesIssuesSpy.mockResolvedValue({
      comicvine_volume_id: 42,
      series_name: 'Stormwatch',
      issues: [],
    })

    render(<ComicVineSearchDialog {...defaultProps({ issueNumber: null })} />)

    const input = screen.getByPlaceholderText('Search series title or paste a ComicVine URL')
    fireEvent.change(input, { target: { value: 'Stormwatch' } })
    await waitFor(() => expect(screen.getByText('Stormwatch')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Stormwatch'))
    await waitFor(() => expect(screen.getByText('No issues found in this series.')).toBeInTheDocument())
  })

  it('shows issue list when issueNumber has no exact match in the series', async () => {
    getSeriesIssuesSpy.mockResolvedValue({
      comicvine_volume_id: 42,
      series_name: 'Stormwatch',
      issues: [mockIssue],
    })

    render(<ComicVineSearchDialog {...defaultProps({ issueNumber: '99' })} />)

    const input = screen.getByPlaceholderText('Search series title or paste a ComicVine URL')
    fireEvent.change(input, { target: { value: 'Stormwatch' } })
    await waitFor(() => expect(screen.getByText('Stormwatch')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Stormwatch'))
    await waitFor(() => expect(screen.getByText('#1')).toBeInTheDocument())
    expect(screen.getByTestId('rematch-issue-context')).toHaveTextContent('#99')
  })

  it('handles getSeriesIssues failure gracefully', async () => {
    getSeriesIssuesSpy.mockRejectedValue(new Error('Network error'))

    render(<ComicVineSearchDialog {...defaultProps({ issueNumber: null })} />)

    const input = screen.getByPlaceholderText('Search series title or paste a ComicVine URL')
    fireEvent.change(input, { target: { value: 'Stormwatch' } })
    await waitFor(() => expect(screen.getByText('Stormwatch')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Stormwatch'))
    await waitFor(() => expect(screen.getByText('Failed to load issues. Please try again.')).toBeInTheDocument())
  })

  it('handles confirm identity failure gracefully', async () => {
    confirmIdentitySpy.mockRejectedValue(new Error('Network error'))

    render(<ComicVineSearchDialog {...defaultProps({ issueNumber: null })} />)

    const input = screen.getByPlaceholderText('Search series title or paste a ComicVine URL')
    fireEvent.change(input, { target: { value: 'Stormwatch' } })
    await waitFor(() => expect(screen.getByText('Stormwatch')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Stormwatch'))
    await waitFor(() => expect(screen.getByText('#1')).toBeInTheDocument())
    fireEvent.click(screen.getByText('#1'))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Confirm Identity' })).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'Confirm Identity' }))
    await waitFor(() => expect(screen.getByText('Failed to confirm identity. Please try again.')).toBeInTheDocument())
  })

  it('shows issue list without auto-selecting when volume URL has no issueNumber match', async () => {
    resolveIdentitySpy.mockResolvedValue({
      input: 'https://comicvine.gamespot.com/superman/4050-148476/',
      kind: 'volume',
      validation_error: null,
      issue: null,
      volume: mockVolume,
      issues: [mockIssue],
    })

    render(<ComicVineSearchDialog {...defaultProps({ issueNumber: '34' })} />)

    const input = screen.getByPlaceholderText('Search series title or paste a ComicVine URL')
    fireEvent.change(input, { target: { value: 'https://comicvine.gamespot.com/superman/4050-148476/' } })

    await waitFor(() => expect(screen.getByText('#1')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: 'Confirm Identity' })).not.toBeInTheDocument()
  })

  it('volume resolution without issueNumber leaves user on select-issue step', async () => {
    resolveIdentitySpy.mockResolvedValue({
      input: 'https://comicvine.gamespot.com/superman/4050-148476/',
      kind: 'volume',
      validation_error: null,
      issue: null,
      volume: mockVolume,
      issues: [mockIssue],
    })

    render(<ComicVineSearchDialog {...defaultProps({ issueNumber: null })} />)

    const input = screen.getByPlaceholderText('Search series title or paste a ComicVine URL')
    fireEvent.change(input, { target: { value: 'https://comicvine.gamespot.com/superman/4050-148476/' } })

    await waitFor(() => expect(screen.getByText('#1')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: 'Confirm Identity' })).not.toBeInTheDocument()
  })

  it('handles clear query to reset pagination and search state', async () => {
    render(<ComicVineSearchDialog {...defaultProps({ threadTitle: '' })} />)

    const input = screen.getByPlaceholderText('Search series title or paste a ComicVine URL')
    fireEvent.change(input, { target: { value: 'X-Men' } })
    await waitFor(() => expect(searchSeriesSpy).toHaveBeenCalled())
    fireEvent.change(input, { target: { value: '' } })

    await waitFor(() => expect(screen.queryByText('Stormwatch')).not.toBeInTheDocument())
  })
})