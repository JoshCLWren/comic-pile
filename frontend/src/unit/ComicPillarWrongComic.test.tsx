import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'

const { confirmIdentitySpy, replaceIdentitySpy, searchSeriesSpy, getSeriesIssuesSpy, getIssueIdentitySpy } =
  vi.hoisted(() => ({
    confirmIdentitySpy: vi.fn().mockResolvedValue({} as never),
    replaceIdentitySpy: vi.fn().mockResolvedValue({} as never),
    searchSeriesSpy: vi.fn(),
    getSeriesIssuesSpy: vi.fn(),
    getIssueIdentitySpy: vi.fn(),
  }))

vi.mock('../services/api', () => ({
  comicVineApi: {
    searchSeries: searchSeriesSpy,
    getSeriesIssues: getSeriesIssuesSpy,
    getIssueIntelligence: vi.fn(),
    getIssueIdentity: getIssueIdentitySpy,
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

vi.mock('../components/IssueCorrectionDialog', () => ({
  default: () => null,
}))

vi.mock('../pages/RollPage/components/ComicIdentity', () => ({
  ComicIdentity: () => <div data-testid="comic-identity-stub" />,
}))

import { ComicPillar } from '../pages/RollPage/components/ComicPillar'

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

const confirmedThread = {
  id: 7,
  title: 'Stormwatch Vol. 1',
  format: 'single',
  issues_remaining: 5,
  queue_position: 1,
  total_issues: 12,
  reading_progress: '58.33',
  issue_id: 43,
  issue_number: '43',
  next_issue_id: 43,
  next_issue_number: '43',
  last_rolled_result: null,
}

describe('ComicPillar Wrong comic? flow', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    getIssueIdentitySpy.mockResolvedValue({
      has_confirmed_identity: true,
      confirmed_mappings: [{ comicvine_id: 36956 }],
    })
    searchSeriesSpy.mockResolvedValue({ query: '', results: [mockSeries], total_available: 1 })
    getSeriesIssuesSpy.mockResolvedValue({
      comicvine_volume_id: 42,
      series_name: 'Stormwatch',
      issues: [mockIssue],
    })
  })

  it('routes a correction opened via Wrong comic? to the replace endpoint', async () => {
    render(<ComicPillar activeRatingThread={confirmedThread} onRefreshThread={vi.fn()} />)

    const wrongComicButton = await screen.findByRole('button', { name: 'Wrong comic?' })
    fireEvent.click(wrongComicButton)

    expect(await screen.findByRole('dialog')).toBeInTheDocument()

    fireEvent.change(screen.getByPlaceholderText('Search series title...'), {
      target: { value: 'Stormwatch' },
    })
    await waitFor(() => expect(searchSeriesSpy).toHaveBeenCalledWith('Stormwatch', 10))
    fireEvent.click(screen.getByText('Stormwatch'))
    await waitFor(() => expect(screen.getByText('#1')).toBeInTheDocument())

    fireEvent.click(screen.getByText('#1'))
    fireEvent.click(screen.getByRole('button', { name: 'Confirm Identity' }))

    await waitFor(() => expect(replaceIdentitySpy).toHaveBeenCalledWith(43, 36956))
    expect(confirmIdentitySpy).not.toHaveBeenCalled()
  })

  it('routes a first-time match via Find ComicVine match to the confirm endpoint', async () => {
    getIssueIdentitySpy.mockResolvedValue({
      has_confirmed_identity: false,
      confirmed_mappings: [],
    })

    render(<ComicPillar activeRatingThread={confirmedThread} onRefreshThread={vi.fn()} />)

    const findMatchButton = await screen.findByRole('button', { name: 'Find ComicVine match' })
    fireEvent.click(findMatchButton)

    expect(await screen.findByRole('dialog')).toBeInTheDocument()

    fireEvent.change(screen.getByPlaceholderText('Search series title...'), {
      target: { value: 'Stormwatch' },
    })
    await waitFor(() => expect(searchSeriesSpy).toHaveBeenCalledWith('Stormwatch', 10))
    fireEvent.click(screen.getByText('Stormwatch'))
    await waitFor(() => expect(screen.getByText('#1')).toBeInTheDocument())

    fireEvent.click(screen.getByText('#1'))
    fireEvent.click(screen.getByRole('button', { name: 'Confirm Identity' }))

    await waitFor(() => expect(confirmIdentitySpy).toHaveBeenCalledWith(43, 36956))
    expect(replaceIdentitySpy).not.toHaveBeenCalled()
  })
})
