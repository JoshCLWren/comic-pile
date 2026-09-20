import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import { queryClient } from '../query/queryClient'
import { queryKeys } from '../query/queryKeys'
import { invalidateComicVineIssueIntelligence } from '../query/cacheEffects'

const { searchSeriesSpy, getSeriesIssuesSpy, getIssueIdentitySpy, confirmIdentitySpy, replaceIdentitySpy } =
  vi.hoisted(() => ({
    searchSeriesSpy: vi.fn(),
    getSeriesIssuesSpy: vi.fn(),
    getIssueIdentitySpy: vi.fn(),
    confirmIdentitySpy: vi.fn().mockResolvedValue({} as never),
    replaceIdentitySpy: vi.fn().mockResolvedValue({} as never),
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

vi.mock('../query/cacheEffects', () => ({
  invalidateComicVineIssueIntelligence: vi.fn(),
  applyComicVineCorrectionOptimistically: vi.fn(),
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

const mockIssueWithCover = {
  comicvine_issue_id: 99999,
  issue_number: '1',
  name: 'New Cover Issue',
  cover_date: '1993-02-01',
  store_date: null,
  image_url: 'https://images.example/new-cover.jpg',
  site_detail_url: null,
}

const mockIssueWithoutCover = {
  comicvine_issue_id: 88888,
  issue_number: '2',
  name: 'No Cover Issue',
  cover_date: '1993-03-01',
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
  issue_id: 77,
  issue_number: '43',
  next_issue_id: 77,
  next_issue_number: '43',
  last_rolled_result: null,
}

describe('ComicPillar cover after ComicVine correction', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    queryClient.clear()
    getIssueIdentitySpy.mockResolvedValue({
      has_confirmed_identity: true,
      confirmed_mappings: [{ comicvine_id: 111 }],
      candidate_mappings: [],
      has_unresolved: false,
      issue_id: 77,
      thread_id: 7,
      thread_title: 'Stormwatch Vol. 1',
    })
    searchSeriesSpy.mockResolvedValue({ query: '', results: [mockSeries], total_available: 1 })
  })

  it('replacing one confirmed identity with another keeps the cover placeholder without remount', async () => {
    getSeriesIssuesSpy.mockResolvedValue({
      comicvine_volume_id: 42,
      series_name: 'Stormwatch',
      issues: [mockIssueWithCover],
    })

    const onRefreshThread = vi.fn()
    const { container } = render(<ComicPillar activeRatingThread={confirmedThread} onRefreshThread={onRefreshThread} />)

    await screen.findByTestId('cover-placeholder')
    expect(onRefreshThread).not.toHaveBeenCalled()

    fireEvent.click(await screen.findByRole('button', { name: 'Wrong series?' }))
    expect(await screen.findByRole('dialog')).toBeInTheDocument()

    fireEvent.change(screen.getByPlaceholderText('Search series title...'), {
      target: { value: 'Stormwatch' },
    })
    await waitFor(() => expect(searchSeriesSpy).toHaveBeenCalledWith('Stormwatch', 10))
    fireEvent.click(screen.getByText('Stormwatch'))
    await waitFor(() => expect(screen.getByText('#1')).toBeInTheDocument())
    fireEvent.click(screen.getByText('#1'))
    fireEvent.click(screen.getByRole('button', { name: 'Confirm Identity' }))

    await waitFor(() => expect(replaceIdentitySpy).toHaveBeenCalledWith(77, 99999))
    await waitFor(() => expect(invalidateComicVineIssueIntelligence).toHaveBeenCalled())
    await waitFor(() => expect(onRefreshThread).toHaveBeenCalled())
    await screen.findByTestId('cover-placeholder')
    expect(queryClient.getQueryData(queryKeys.comicVine.issueIntelligence(999))).toBeUndefined()
    expect(container).toBeInTheDocument()
  })

  it('correction to an issue with no cover shows placeholder and does not spin forever', async () => {
    getSeriesIssuesSpy.mockResolvedValue({
      comicvine_volume_id: 42,
      series_name: 'Stormwatch',
      issues: [mockIssueWithoutCover],
    })

    render(<ComicPillar activeRatingThread={confirmedThread} onRefreshThread={vi.fn()} />)
    await screen.findByTestId('cover-placeholder')

    fireEvent.click(await screen.findByRole('button', { name: 'Wrong series?' }))
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
    fireEvent.change(screen.getByPlaceholderText('Search series title...'), {
      target: { value: 'Stormwatch' },
    })
    await waitFor(() => expect(searchSeriesSpy).toHaveBeenCalledWith('Stormwatch', 10))
    fireEvent.click(screen.getByText('Stormwatch'))
    await waitFor(() => expect(screen.getByText('#2')).toBeInTheDocument())
    fireEvent.click(screen.getByText('#2'))
    fireEvent.click(screen.getByRole('button', { name: 'Confirm Identity' }))

    await waitFor(() => expect(replaceIdentitySpy).toHaveBeenCalledWith(77, 88888))
    await waitFor(() => expect(screen.getByTestId('cover-placeholder')).toBeInTheDocument())
    expect(screen.queryByAltText('')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Loading comic details')).not.toBeInTheDocument()
  })

  it('invalidates only the specific issueIntelligence query, not unrelated caches', async () => {
    const unrelatedIssueId = 123
    queryClient.setQueryData(queryKeys.comicVine.issueIntelligence(unrelatedIssueId), { image_url: 'https://images.example/other.jpg' })
    queryClient.setQueryData(queryKeys.queue.pages(), { pages: [], pageParams: [] } as never)

    getSeriesIssuesSpy.mockResolvedValue({
      comicvine_volume_id: 42,
      series_name: 'Stormwatch',
      issues: [mockIssueWithCover],
    })

    render(<ComicPillar activeRatingThread={confirmedThread} onRefreshThread={vi.fn()} />)
    await screen.findByTestId('cover-placeholder')

    fireEvent.click(await screen.findByRole('button', { name: 'Wrong series?' }))
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
    fireEvent.change(screen.getByPlaceholderText('Search series title...'), {
      target: { value: 'Stormwatch' },
    })
    await waitFor(() => expect(searchSeriesSpy).toHaveBeenCalled())
    fireEvent.click(screen.getByText('Stormwatch'))
    await waitFor(() => expect(screen.getByText('#1')).toBeInTheDocument())
    fireEvent.click(screen.getByText('#1'))
    fireEvent.click(screen.getByRole('button', { name: 'Confirm Identity' }))
    await waitFor(() => expect(replaceIdentitySpy).toHaveBeenCalled())
    await waitFor(() => expect(invalidateComicVineIssueIntelligence).toHaveBeenCalledWith(
      expect.anything(),
      77,
    ))

    const other = queryClient.getQueryData(queryKeys.comicVine.issueIntelligence(unrelatedIssueId)) as { image_url: string } | undefined
    expect(other?.image_url).toBe('https://images.example/other.jpg')
  })
})
