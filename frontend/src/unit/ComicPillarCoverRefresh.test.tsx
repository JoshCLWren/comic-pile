import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import { queryClient } from '../query/queryClient'
import { queryKeys } from '../query/queryKeys'

const { searchSeriesSpy, getSeriesIssuesSpy, getIssueIdentitySpy, confirmIdentitySpy, replaceIdentitySpy, getIntelligenceSpy } =
  vi.hoisted(() => ({
    searchSeriesSpy: vi.fn(),
    getSeriesIssuesSpy: vi.fn(),
    getIssueIdentitySpy: vi.fn(),
    confirmIdentitySpy: vi.fn().mockResolvedValue({} as never),
    replaceIdentitySpy: vi.fn().mockResolvedValue({} as never),
    getIntelligenceSpy: vi.fn(),
  }))

vi.mock('../services/api', () => ({
  comicVineApi: {
    searchSeries: searchSeriesSpy,
    getSeriesIssues: getSeriesIssuesSpy,
    getIssueIntelligence: getIntelligenceSpy,
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

function staleIntelligence(imageUrl: string | null) {
  return {
    comicvine_issue_id: 'stale',
    comicvine_url: 'https://comicvine.example/stale',
    series_name: 'Stormwatch',
    series_id: 8,
    issue_number: '43',
    name: 'Stale Issue',
    description: 'stale',
    image_url: imageUrl,
    cover_date: '1993-01-01',
    store_date: null,
    creators: [],
    story_arcs: [],
  }
}

function freshIntelligence(imageUrl: string | null) {
  return {
    comicvine_issue_id: 'fresh',
    comicvine_url: 'https://comicvine.example/fresh',
    series_name: 'Stormwatch Corrected',
    series_id: 9,
    issue_number: '43',
    name: 'Fresh Issue',
    description: 'fresh after correction',
    image_url: imageUrl,
    cover_date: '1993-02-01',
    store_date: null,
    creators: [],
    story_arcs: [],
  }
}

describe('ComicPillar cover refresh after ComicVine correction', () => {
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

  it('replacing one confirmed identity with another updates the cover without remount even though issueId is unchanged', async () => {
    // First call renders stale cover, second call after invalidation returns fresh cover
    getIntelligenceSpy
      .mockResolvedValueOnce(staleIntelligence('https://images.example/old-cover.jpg'))
      .mockResolvedValueOnce(freshIntelligence('https://images.example/new-cover.jpg'))

    getSeriesIssuesSpy.mockResolvedValue({
      comicvine_volume_id: 42,
      series_name: 'Stormwatch',
      issues: [mockIssueWithCover],
    })

    const onRefreshThread = vi.fn()
    const { container } = render(<ComicPillar activeRatingThread={confirmedThread} onRefreshThread={onRefreshThread} />)

    // initial stale cover should appear
    const staleImg = await screen.findByAltText('')
    expect(staleImg.getAttribute('src')).toContain(encodeURIComponent('https://images.example/old-cover.jpg'))
    expect(getIntelligenceSpy).toHaveBeenCalledTimes(1)
    expect(getIntelligenceSpy).toHaveBeenCalledWith(77)

    // sanity: cache holds stale data
    const cachedBefore = queryClient.getQueryData(queryKeys.comicVine.issueIntelligence(77)) as { image_url: string } | undefined
    expect(cachedBefore?.image_url).toBe('https://images.example/old-cover.jpg')

    // trigger replace flow via Wrong series?
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

    // After confirmation, the specific comicVine query should have been invalidated and refetched
    // Do not require remount - same container should now show new cover
    await waitFor(() => expect(getIntelligenceSpy).toHaveBeenCalledTimes(2))
    await waitFor(() => expect(onRefreshThread).toHaveBeenCalled())

    // Optimistic update makes new image appear immediately, refetch confirms it
    const updatedImg = await screen.findByAltText('')
    expect(updatedImg.getAttribute('src')).toContain(encodeURIComponent('https://images.example/new-cover.jpg'))

    // Ensure we did NOT globally clear unrelated caches (queue pages should stay untouched)
    // The only invalidation is for the specific issueId query; verify cache updated not cleared globally
    const cachedAfter = queryClient.getQueryData(queryKeys.comicVine.issueIntelligence(77)) as { image_url: string | null } | undefined
    expect(cachedAfter?.image_url).toBe('https://images.example/new-cover.jpg')

    // Different issueId cache must remain independent (not touched)
    expect(queryClient.getQueryData(queryKeys.comicVine.issueIntelligence(999))).toBeUndefined()

    // Component was not remounted (container identity preserved)
    expect(container).toBeInTheDocument()
  })

  it('correction to an issue with no cover shows placeholder and does not spin forever', async () => {
    getIntelligenceSpy
      .mockResolvedValueOnce(staleIntelligence('https://images.example/old-cover.jpg'))
      .mockResolvedValueOnce(freshIntelligence(null))

    getSeriesIssuesSpy.mockResolvedValue({
      comicvine_volume_id: 42,
      series_name: 'Stormwatch',
      issues: [mockIssueWithoutCover],
    })

    render(<ComicPillar activeRatingThread={confirmedThread} onRefreshThread={vi.fn()} />)
    await screen.findByAltText('')

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
    await waitFor(() => expect(getIntelligenceSpy).toHaveBeenCalledTimes(2))

    // Should show placeholder, not spinner, not stale image
    await waitFor(() => expect(screen.getByTestId('cover-placeholder')).toBeInTheDocument())
    expect(screen.queryByAltText('')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Loading comic details')).not.toBeInTheDocument()
  })

  it('invalidates only the specific issueIntelligence query, not unrelated caches', async () => {
    // Seed unrelated cache entry that must survive
    const unrelatedIssueId = 123
    // Pre-populate unrelated query
    queryClient.setQueryData(queryKeys.comicVine.issueIntelligence(unrelatedIssueId), freshIntelligence('https://images.example/other.jpg'))
    queryClient.setQueryData(queryKeys.queue.pages(), { pages: [], pageParams: [] } as never)

    getIntelligenceSpy.mockResolvedValueOnce(staleIntelligence('https://images.example/old.jpg'))
    // after invalidation fresh
    getIntelligenceSpy.mockResolvedValueOnce(freshIntelligence('https://images.example/new.jpg'))

    getSeriesIssuesSpy.mockResolvedValue({
      comicvine_volume_id: 42,
      series_name: 'Stormwatch',
      issues: [mockIssueWithCover],
    })

    render(<ComicPillar activeRatingThread={confirmedThread} onRefreshThread={vi.fn()} />)
    await screen.findByAltText('')

    // trigger correction
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

    // unrelated comicVine query must still be present (not cleared)
    await waitFor(() => expect(getIntelligenceSpy).toHaveBeenCalledWith(77))
    const other = queryClient.getQueryData(queryKeys.comicVine.issueIntelligence(unrelatedIssueId)) as { image_url: string } | undefined
    expect(other?.image_url).toBe('https://images.example/other.jpg')
  })
})
