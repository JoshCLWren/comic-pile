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
  default: ({ isOpen, title, children }: { isOpen: boolean; title: string; children: ReactNode }) =>
    isOpen ? <div role="dialog"><h2>{title}</h2>{children}</div> : null,
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
    await waitFor(() => expect(screen.getByText('#1')).toBeInTheDocument())

    fireEvent.click(screen.getByText('#1'))
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
    await waitFor(() => expect(screen.getByText('#1')).toBeInTheDocument())

    fireEvent.click(screen.getByText('#1'))
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