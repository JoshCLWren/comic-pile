import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'

const { confirmIdentitySpy, replaceIdentitySpy, searchSeriesSpy, getSeriesIssuesSpy, resolveIdentitySpy } = vi.hoisted(() => ({
  // SAFETY: mock payload supplies only the fields this test asserts
  confirmIdentitySpy: vi.fn().mockResolvedValue({} as never),
  // SAFETY: mock payload supplies only the fields this test asserts
  replaceIdentitySpy: vi.fn().mockResolvedValue({} as never),
  searchSeriesSpy: vi.fn(),
  getSeriesIssuesSpy: vi.fn(),
  resolveIdentitySpy: vi.fn(),
}))

vi.mock('../services/api-comicvine', () => ({
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

const {
  commitMappingMutateMock,
  useSiblingSeriesMappingPreviewMock,
  useCommitSeriesMappingMock,
} = vi.hoisted(() => {
  const commitMappingMutateMock = vi.fn()
  return {
    commitMappingMutateMock,
    useSiblingSeriesMappingPreviewMock: vi.fn(() => ({
      data: {
        preview_token: 'sibling-tok',
        scope: { status: 'available' as const, scope_key: 'k', origin_issue_id: 1, series_label: 'Saga', basis: 'b' },
        provider_series: null,
        counts: { already_confirmed: 0, safe_exact_match: 0, needs_review_ambiguous: 0, needs_review_conflict: 0, unresolved: 0, excluded_special: 0 },
        rows: [
          {
            row_id: 'issue:1',
            issue_id: 1,
            issue_number: '1',
            title: 'Saga #1',
            classification: 'already_confirmed',
            thread_id: 10,
            thread_title: 'Saga',
            current_mapping_status: null,
            proposed_mapping: false,
            default_selected: false,
            reason: null,
          },
          {
            row_id: 'issue:2',
            issue_id: 2,
            issue_number: '2',
            title: 'Saga #2',
            classification: 'safe_exact_match',
            thread_id: 10,
            thread_title: 'Saga',
            current_mapping_status: null,
            proposed_mapping: true,
            default_selected: true,
            reason: null,
          },
        ],
        issued_at: 1,
        expires_at: null,
      },
      isPending: false,
      isError: false,
      refetch: vi.fn(),
      reset: vi.fn(),
    })),
    useCommitSeriesMappingMock: vi.fn(() => ({
      mutate: commitMappingMutateMock,
      isPending: false,
      isError: false,
      isSuccess: false,
      data: null,
      error: null,
      reset: vi.fn(),
    })),
  }
})

vi.mock('../hooks/useSiblingSeriesMapping', () => ({
  useSiblingSeriesMappingPreview: useSiblingSeriesMappingPreviewMock,
  useCommitSeriesMapping: useCommitSeriesMappingMock,
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
  // SAFETY: the literal is one of the dialog modes under test
  mode: 'confirm' as 'confirm' | 'replace',
  onClose: vi.fn(),
  onConfirmed: vi.fn(),
  ...overrides,
})

/** The dialog debounces keystrokes before it asks the provider; tests must outlast it. */
const SEARCH_DEBOUNCE_MS = 350

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
      input: 'https://fallback.test/search?q=plain',
      kind: 'search',
      validation_error: null,
      issue: null,
      volume: null,
      issues: [],
    })

    render(<ComicVineSearchDialog {...defaultProps()} />)

    await waitFor(() => expect(searchSeriesSpy).toHaveBeenCalled())
    searchSeriesSpy.mockClear()

    const input = screen.getByPlaceholderText('Search series title or paste a ComicVine URL')
    fireEvent.change(input, { target: { value: 'https://fallback.test/search?q=plain' } })

    await waitFor(() => {
      expect(searchSeriesSpy).toHaveBeenCalledWith('https://fallback.test/search?q=plain', 10, 0)
    })
    expect(screen.getByPlaceholderText('Search series title or paste a ComicVine URL')).toBeInTheDocument()
    expect(confirmIdentitySpy).not.toHaveBeenCalled()
  })

  it('handles volume resolution with null volume data', async () => {
    resolveIdentitySpy.mockResolvedValue({
      input: 'https://comicvine.gamespot.com/superman/4050-148476/',
      kind: 'volume',
      validation_error: null,
      issue: null,
      volume: null,
      issues: [],
    })

    render(<ComicVineSearchDialog {...defaultProps()} />)

    await waitFor(() => expect(searchSeriesSpy).toHaveBeenCalled())
    searchSeriesSpy.mockClear()

    const input = screen.getByPlaceholderText('Search series title or paste a ComicVine URL')
    fireEvent.change(input, { target: { value: 'https://comicvine.gamespot.com/superman/4050-148476/' } })

    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent('Failed to resolve ComicVine volume. Please try again.'),
    )
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

describe('ComicVineSearchDialog sibling mapping offer (#3159)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // Earlier suites install one-shot reject implementations that outlive
    // clearAllMocks, so reset each collaborator before this suite asserts on the
    // happy confirmation path.
    confirmIdentitySpy.mockReset()
    confirmIdentitySpy.mockResolvedValue({})
    searchSeriesSpy.mockReset()
    searchSeriesSpy.mockResolvedValue({ query: '', results: [mockSeries], total_available: 1, offset: 0, limit: 10, has_more: false, next_offset: null })
    getSeriesIssuesSpy.mockReset()
    getSeriesIssuesSpy.mockResolvedValue({ comicvine_volume_id: 42, series_name: 'Stormwatch', issues: [mockIssue] })
  })

  it('offers the series siblings after confirming an identity with a volume', async () => {
    render(<ComicVineSearchDialog {...defaultProps()} />)

    const input = screen.getByPlaceholderText('Search series title or paste a ComicVine URL')
    fireEvent.change(input, { target: { value: 'Stormwatch' } })
    await waitFor(() => expect(screen.getByText('Stormwatch')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Stormwatch'))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Confirm Identity' })).toBeInTheDocument())

    expect(confirmIdentitySpy).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Confirm Identity' }))

    await waitFor(() => expect(confirmIdentitySpy).toHaveBeenCalledWith(43, 36956))
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Map Sibling Issues' })).toBeInTheDocument())
    expect(screen.getByTestId('sibling-mapping-offer')).toBeInTheDocument()
    expect(screen.queryByPlaceholderText('Search series title or paste a ComicVine URL')).not.toBeInTheDocument()
  })

  it('passes the confirmed volume to the sibling offer and keeps the dialog open', async () => {
    render(<ComicVineSearchDialog {...defaultProps()} />)

    const input = screen.getByPlaceholderText('Search series title or paste a ComicVine URL')
    fireEvent.change(input, { target: { value: 'Stormwatch' } })
    await waitFor(() => expect(screen.getByText('Stormwatch')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Stormwatch'))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Confirm Identity' })).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'Confirm Identity' }))

    await waitFor(() => expect(screen.getByTestId('sibling-mapping-offer')).toBeInTheDocument())
    expect(useSiblingSeriesMappingPreviewMock).toHaveBeenCalledWith(43, 'comicvine', '42')
  })

  it('closes the dialog instead of offering siblings when the confirmed volume is missing', async () => {
    const onClose = vi.fn()
    searchSeriesSpy.mockResolvedValue({
      query: 'Stormwatch',
      results: [{ ...mockSeries, comicvine_volume_id: null }],
      total_available: 1,
      offset: 0,
      limit: 10,
      has_more: false,
      next_offset: null,
    })
    render(<ComicVineSearchDialog {...defaultProps({ onClose })} />)

    const input = screen.getByPlaceholderText('Search series title or paste a ComicVine URL')
    fireEvent.change(input, { target: { value: 'Stormwatch' } })
    await waitFor(() => expect(screen.getByText('Stormwatch')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Stormwatch'))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Confirm Identity' })).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'Confirm Identity' }))

    await waitFor(() => expect(onClose).toHaveBeenCalled())
    expect(screen.queryByTestId('sibling-mapping-offer')).not.toBeInTheDocument()
  })

  it('reports confirmed sibling issues back to the caller', async () => {
    const onSiblingsMapped = vi.fn()
    render(<ComicVineSearchDialog {...defaultProps({ onSiblingsMapped })} />)

    const input = screen.getByPlaceholderText('Search series title or paste a ComicVine URL')
    fireEvent.change(input, { target: { value: 'Stormwatch' } })
    await waitFor(() => expect(screen.getByText('Stormwatch')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Stormwatch'))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Confirm Identity' })).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'Confirm Identity' }))

    await waitFor(() => expect(screen.getByTestId('sibling-mapping-offer')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('sibling-mapping-approve'))

    expect(commitMappingMutateMock).toHaveBeenCalledTimes(1)
    const commitHandlers = commitMappingMutateMock.mock.calls[0][1]
    commitHandlers.onSuccess({ confirmed_issue_ids: [7, 8] })

    expect(onSiblingsMapped).toHaveBeenCalledWith([7, 8])
  })

  it('closes the dialog when the reader finishes the sibling offer', async () => {
    const onClose = vi.fn()
    render(<ComicVineSearchDialog {...defaultProps({ onClose })} />)

    const input = screen.getByPlaceholderText('Search series title or paste a ComicVine URL')
    fireEvent.change(input, { target: { value: 'Stormwatch' } })
    await waitFor(() => expect(screen.getByText('Stormwatch')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Stormwatch'))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Confirm Identity' })).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'Confirm Identity' }))

    await waitFor(() => expect(screen.getByTestId('sibling-mapping-offer')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('sibling-mapping-dismiss'))

    expect(onClose).toHaveBeenCalled()
  })
})

describe('ComicVineSearchDialog single-state loading (#3448)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    searchSeriesSpy.mockResolvedValue({ query: '', results: [mockSeries], total_available: 1, offset: 0, limit: 10, has_more: false, next_offset: null })
    getSeriesIssuesSpy.mockResolvedValue({ comicvine_volume_id: 42, series_name: 'Stormwatch', issues: [mockIssue] })
  })

  function deferred<T>() {
    let resolve: (value: T) => void = () => {}
    let reject: (reason?: unknown) => void = () => {}
    const promise = new Promise<T>((res, rej) => {
      resolve = res
      reject = rej
    })
    return { promise, resolve, reject }
  }

  type SeriesResponse = {
    query: string
    results: (typeof mockSeries)[]
    total_available: number
    offset: number
    limit: number
    has_more: boolean
    next_offset: number | null
  }

  it('clears stale series results and the spinner when a search fails', async () => {
    const { container } = render(<ComicVineSearchDialog {...defaultProps({ threadTitle: '' })} />)
    const input = screen.getByPlaceholderText('Search series title or paste a ComicVine URL')

    fireEvent.change(input, { target: { value: 'Stormwatch' } })
    await waitFor(() => expect(screen.getByText('Stormwatch')).toBeInTheDocument())

    searchSeriesSpy.mockRejectedValueOnce(new Error('provider down'))
    fireEvent.change(input, { target: { value: 'Stormwatch Fails' } })

    await waitFor(() =>
      expect(screen.getByText('Failed to search ComicVine. Please try again.')).toBeInTheDocument(),
    )
    expect(screen.queryByText('Stormwatch')).not.toBeInTheDocument()
    expect(container.querySelector('.animate-spin')).toBeNull()
    expect(screen.getByTestId('comicvine-retry')).toBeInTheDocument()
  })

  it('retries a failed search and recovers without a stale error', async () => {
    render(<ComicVineSearchDialog {...defaultProps({ threadTitle: '' })} />)
    const input = screen.getByPlaceholderText('Search series title or paste a ComicVine URL')

    searchSeriesSpy.mockRejectedValueOnce(new Error('provider down'))
    fireEvent.change(input, { target: { value: 'Recover Query' } })
    await waitFor(() => expect(screen.getByTestId('comicvine-retry')).toBeInTheDocument())

    searchSeriesSpy.mockResolvedValueOnce({
      query: 'Recover Query',
      results: [{ ...mockSeries, name: 'Recovered Series' }],
      total_available: 1,
      offset: 0,
      limit: 10,
      has_more: false,
      next_offset: null,
    })
    fireEvent.click(screen.getByTestId('comicvine-retry'))

    await waitFor(() => expect(screen.getByText('Recovered Series')).toBeInTheDocument())
    expect(searchSeriesSpy).toHaveBeenLastCalledWith('Recover Query', 10, 0)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('never shows "No match" while the issue list failed to load, and retry refetches', async () => {
    render(<ComicVineSearchDialog {...defaultProps({ issueNumber: '40' })} />)
    const input = screen.getByPlaceholderText('Search series title or paste a ComicVine URL')

    fireEvent.change(input, { target: { value: 'Stormwatch' } })
    await waitFor(() => expect(screen.getByText('Stormwatch')).toBeInTheDocument())

    getSeriesIssuesSpy.mockRejectedValueOnce(new Error('provider down'))
    fireEvent.click(screen.getByText('Stormwatch'))

    await waitFor(() =>
      expect(screen.getByText('Failed to load issues. Please try again.')).toBeInTheDocument(),
    )
    expect(screen.queryByText(/No match for #40/)).not.toBeInTheDocument()

    getSeriesIssuesSpy.mockResolvedValueOnce({
      comicvine_volume_id: 42,
      series_name: 'Stormwatch',
      issues: [{ ...mockIssue, issue_number: '40', name: 'Forty' }],
    })
    fireEvent.click(screen.getByTestId('comicvine-retry'))

    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Confirm Identity' })).toBeInTheDocument(),
    )
    expect(getSeriesIssuesSpy).toHaveBeenLastCalledWith(42, 'Stormwatch')
  })

  it('ignores an out-of-order series response so the latest query wins', async () => {
    const first = deferred<SeriesResponse>()
    const second = deferred<SeriesResponse>()
    searchSeriesSpy.mockImplementation((searchQuery: string) =>
      searchQuery === 'First Query' ? first.promise : second.promise,
    )

    render(<ComicVineSearchDialog {...defaultProps({ threadTitle: '' })} />)
    const input = screen.getByPlaceholderText('Search series title or paste a ComicVine URL')

    fireEvent.change(input, { target: { value: 'First Query' } })
    await waitFor(() => expect(searchSeriesSpy).toHaveBeenCalledWith('First Query', 10, 0))

    fireEvent.change(input, { target: { value: 'Second Query' } })
    await waitFor(() => expect(searchSeriesSpy).toHaveBeenCalledWith('Second Query', 10, 0))

    await act(async () => {
      second.resolve({
        query: 'Second Query',
        results: [{ ...mockSeries, comicvine_volume_id: 22, name: 'Second Series' }],
        total_available: 1,
        offset: 0,
        limit: 10,
        has_more: false,
        next_offset: null,
      })
    })
    expect(screen.getByText('Second Series')).toBeInTheDocument()

    await act(async () => {
      first.resolve({
        query: 'First Query',
        results: [{ ...mockSeries, comicvine_volume_id: 11, name: 'First Series' }],
        total_available: 1,
        offset: 0,
        limit: 10,
        has_more: false,
        next_offset: null,
      })
    })
    expect(screen.getByText('Second Series')).toBeInTheDocument()
    expect(screen.queryByText('First Series')).not.toBeInTheDocument()
  })

  it('ignores a stale response that lands while a newer query is still debouncing', async () => {
    const first = deferred<SeriesResponse>()
    const second = deferred<SeriesResponse>()
    searchSeriesSpy.mockImplementation((searchQuery: string) =>
      searchQuery === 'First Query' ? first.promise : second.promise,
    )

    render(<ComicVineSearchDialog {...defaultProps({ threadTitle: '' })} />)
    const input = screen.getByPlaceholderText('Search series title or paste a ComicVine URL')

    fireEvent.change(input, { target: { value: 'First Query' } })
    await waitFor(() => expect(searchSeriesSpy).toHaveBeenCalledWith('First Query', 10, 0))

    fireEvent.change(input, { target: { value: 'Second Query' } })
    await act(async () => {
      first.resolve({
        query: 'First Query',
        results: [{ ...mockSeries, comicvine_volume_id: 11, name: 'First Series' }],
        total_available: 1,
        offset: 0,
        limit: 10,
        has_more: false,
        next_offset: null,
      })
    })

    expect(screen.queryByText('First Series')).not.toBeInTheDocument()
  })

  it('ignores a stale response that lands after the reader clears the query', async () => {
    const first = deferred<SeriesResponse>()
    searchSeriesSpy.mockImplementationOnce(() => first.promise)

    render(<ComicVineSearchDialog {...defaultProps({ threadTitle: '' })} />)
    const input = screen.getByPlaceholderText('Search series title or paste a ComicVine URL')

    fireEvent.change(input, { target: { value: 'Abandoned Query' } })
    await waitFor(() => expect(searchSeriesSpy).toHaveBeenCalledWith('Abandoned Query', 10, 0))

    fireEvent.change(input, { target: { value: '' } })
    await waitFor(() =>
      expect(screen.getByText('Type a series name to search ComicVine')).toBeInTheDocument(),
    )

    await act(async () => {
      first.resolve({
        query: 'Abandoned Query',
        results: [{ ...mockSeries, comicvine_volume_id: 21, name: 'Abandoned Series' }],
        total_available: 1,
        offset: 0,
        limit: 10,
        has_more: false,
        next_offset: null,
      })
    })

    // Clearing the field abandons the query, so its late response must not repopulate the
    // result list next to the "type a series name" hint.
    expect(screen.queryByText('Abandoned Series')).not.toBeInTheDocument()
    expect(screen.getByText('Type a series name to search ComicVine')).toBeInTheDocument()
  })

  it('ignores a stale response that lands after the dialog context resets', async () => {
    const first = deferred<SeriesResponse>()
    searchSeriesSpy.mockImplementationOnce(() => first.promise)

    const { rerender } = render(
      <ComicVineSearchDialog {...defaultProps({ threadTitle: 'Stormwatch Vol. 1' })} />,
    )
    await waitFor(() => expect(searchSeriesSpy).toHaveBeenCalledWith('Stormwatch Vol. 1', 10, 0))

    rerender(<ComicVineSearchDialog {...defaultProps({ threadTitle: 'The Authority' })} />)
    expect(
      screen.getByPlaceholderText('Search series title or paste a ComicVine URL'),
    ).toHaveValue('The Authority')

    await act(async () => {
      first.resolve({
        query: 'Stormwatch Vol. 1',
        results: [{ ...mockSeries, comicvine_volume_id: 31, name: 'Stale Series' }],
        total_available: 1,
        offset: 0,
        limit: 10,
        has_more: false,
        next_offset: null,
      })
    })

    expect(screen.queryByText('Stale Series')).not.toBeInTheDocument()
  })

  it('does not carry a failed issue load back onto the search screen', async () => {
    render(<ComicVineSearchDialog {...defaultProps({ issueNumber: '40' })} />)
    const input = screen.getByPlaceholderText('Search series title or paste a ComicVine URL')

    fireEvent.change(input, { target: { value: 'Stormwatch' } })
    await waitFor(() => expect(screen.getByText('Stormwatch')).toBeInTheDocument())

    getSeriesIssuesSpy.mockRejectedValueOnce(new Error('provider down'))
    fireEvent.click(screen.getByText('Stormwatch'))

    await waitFor(() =>
      expect(screen.getByText('Failed to load issues. Please try again.')).toBeInTheDocument(),
    )

    fireEvent.click(screen.getByRole('button', { name: '← Back to search' }))

    // The issue step's failure belongs to the issue step: the search screen must not inherit
    // an error (or a retry that would re-run the wrong request) it cannot act on.
    await waitFor(() =>
      expect(
        screen.queryByText('Failed to load issues. Please try again.'),
      ).not.toBeInTheDocument(),
    )
    expect(screen.queryByTestId('comicvine-retry')).not.toBeInTheDocument()
    expect(screen.getByText('Stormwatch')).toBeInTheDocument()
  })

  it('ignores a late issue success after the reader returns to search', async () => {
    const issues = deferred<{
      comicvine_volume_id: number
      series_name: string
      issues: (typeof mockIssue)[]
    }>()
    getSeriesIssuesSpy.mockImplementationOnce(() => issues.promise)

    render(<ComicVineSearchDialog {...defaultProps({ issueNumber: '40' })} />)
    const input = screen.getByPlaceholderText('Search series title or paste a ComicVine URL')

    fireEvent.change(input, { target: { value: 'Stormwatch' } })
    await waitFor(() => expect(screen.getByText('Stormwatch')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Stormwatch'))

    // The reader leaves the issue step while its request is still outstanding.
    fireEvent.click(await screen.findByRole('button', { name: '← Back to search' }))

    await act(async () => {
      issues.resolve({
        comicvine_volume_id: 42,
        series_name: 'Stormwatch',
        issues: [{ ...mockIssue, issue_number: '40', name: 'Forty' }],
      })
    })

    // The abandoned request must not pull the reader onto the confirm step.
    expect(
      screen.getByPlaceholderText('Search series title or paste a ComicVine URL'),
    ).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Confirm Identity' })).not.toBeInTheDocument()
  })

  it('ignores a late issue failure after the reader returns to search', async () => {
    const issues = deferred<{
      comicvine_volume_id: number
      series_name: string
      issues: (typeof mockIssue)[]
    }>()
    getSeriesIssuesSpy.mockImplementationOnce(() => issues.promise)

    render(<ComicVineSearchDialog {...defaultProps({ issueNumber: '40' })} />)
    const input = screen.getByPlaceholderText('Search series title or paste a ComicVine URL')

    fireEvent.change(input, { target: { value: 'Stormwatch' } })
    await waitFor(() => expect(screen.getByText('Stormwatch')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Stormwatch'))

    fireEvent.click(await screen.findByRole('button', { name: '← Back to search' }))

    await act(async () => {
      issues.reject(new Error('provider down'))
    })

    expect(
      screen.queryByText('Failed to load issues. Please try again.'),
    ).not.toBeInTheDocument()
    expect(
      screen.getByPlaceholderText('Search series title or paste a ComicVine URL'),
    ).toBeInTheDocument()
  })

  it('cancels a still-debouncing query when the reader closes the dialog', async () => {
    const abandoned = deferred<SeriesResponse>()
    searchSeriesSpy.mockImplementationOnce(() => abandoned.promise)

    const { rerender } = render(<ComicVineSearchDialog {...defaultProps({ threadTitle: '' })} />)
    const input = screen.getByPlaceholderText('Search series title or paste a ComicVine URL')

    // Dismissing inside the debounce window must cancel the armed timer instead of leaving
    // it to ask the provider for a term the reader already walked away from (#3872).
    fireEvent.change(input, { target: { value: 'Stormwatch' } })
    rerender(<ComicVineSearchDialog {...defaultProps({ threadTitle: '', isOpen: false })} />)

    // Outlast the debounce window the abandoned keystroke had already armed.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, SEARCH_DEBOUNCE_MS + 150))
    })
    await act(async () => {
      abandoned.resolve({
        query: 'Stormwatch',
        results: [{ ...mockSeries, comicvine_volume_id: 31, name: 'Abandoned Series' }],
        total_available: 1,
        offset: 0,
        limit: 10,
        has_more: false,
        next_offset: null,
      })
    })

    expect(searchSeriesSpy).not.toHaveBeenCalled()
    expect(screen.queryByText('Abandoned Series')).not.toBeInTheDocument()
  })
})

