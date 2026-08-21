import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'

const confirmIdentitySpy = vi.fn().mockResolvedValue({} as never)
const replaceIdentitySpy = vi.fn().mockResolvedValue({} as never)
const searchSeriesSpy = vi.fn()
const getSeriesIssuesSpy = vi.fn()

vi.mock('../../services/api', () => ({
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

vi.mock('../../components/Modal', () => ({
  default: ({ isOpen, title, children }: { isOpen: boolean; title: string; children: ReactNode }) =>
    isOpen ? <div role="dialog"><h2>{title}</h2>{children}</div> : null,
}))

import ComicVineSearchDialog from '../../components/ComicVineSearchDialog'

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

    fireEvent.click(screen.getByText('Stormwatch'))
    await waitFor(() => expect(screen.getByText('#1')).toBeInTheDocument())

    fireEvent.click(screen.getByText('#1'))
    fireEvent.click(screen.getByRole('button', { name: 'Confirm Identity' }))

    await waitFor(() => expect(confirmIdentitySpy).toHaveBeenCalledWith(43, 36956))
    expect(replaceIdentitySpy).not.toHaveBeenCalled()
  })

  it('calls replaceIdentity in replace mode when the user confirms a selection', async () => {
    render(<ComicVineSearchDialog {...defaultProps({ mode: 'replace' })} />)

    fireEvent.click(screen.getByText('Stormwatch'))
    await waitFor(() => expect(screen.getByText('#1')).toBeInTheDocument())

    fireEvent.click(screen.getByText('#1'))
    fireEvent.click(screen.getByRole('button', { name: 'Confirm Identity' }))

    await waitFor(() => expect(replaceIdentitySpy).toHaveBeenCalledWith(43, 36956))
    expect(confirmIdentitySpy).not.toHaveBeenCalled()
  })
})