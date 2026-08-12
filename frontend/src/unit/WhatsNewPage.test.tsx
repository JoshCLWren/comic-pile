import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import WhatsNewPage, {
  groupReleasesByDay,
  RELEASE_PAGE_SIZE,
  sortReleasesNewestFirst,
} from '../pages/WhatsNewPage'
import { releasesApi, type Release } from '../services/api-releases'

vi.mock('../services/api-releases', () => ({
  releasesApi: {
    list: vi.fn(),
  },
}))

const api = vi.mocked(releasesApi)

function release(overrides: Partial<Release> = {}): Release {
  return {
    id: 1,
    source_repository: 'JoshCLWren/comic-pile',
    source_pr_number: null,
    source_merge_sha: null,
    merged_at: null,
    released_at: '2026-08-11T20:00:00Z',
    category: 'Queue',
    title: 'Queue cards open details',
    summary: 'Selecting a Queue card now opens its thread details reliably.',
    body: null,
    visibility: 'public',
    status: 'published',
    sort_order: 0,
    provenance_json: {},
    created_at: '2026-08-11T20:00:00Z',
    updated_at: '2026-08-11T20:00:00Z',
    ...overrides,
  } as Release
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('release ordering helpers', () => {
  it('orders releases newest-first with deterministic same-time tie breakers', () => {
    const releases = [
      release({ id: 2, sort_order: 1, released_at: '2026-08-10T20:00:00Z' }),
      release({ id: 3, sort_order: 2 }),
      release({ id: 1, sort_order: 1 }),
    ]

    expect(sortReleasesNewestFirst(releases).map(item => item.id)).toEqual([3, 1, 2])
  })

  it('groups historical and PR-backed releases by localized release day', () => {
    const days = groupReleasesByDay([
      release({ id: 3, source_pr_number: 1096, released_at: '2026-08-11T20:00:00Z' }),
      release({ id: 2, source_pr_number: null, released_at: '2026-08-11T10:00:00Z' }),
      release({ id: 1, source_pr_number: null, released_at: '2026-08-10T20:00:00Z' }),
    ], 'UTC')

    expect(days).toHaveLength(2)
    expect(days[0].releases.map(item => item.id)).toEqual([3, 2])
    expect(days[1].releases.map(item => item.id)).toEqual([1])
  })
})

describe('WhatsNewPage', () => {
  it('shows loading and then the empty release-ledger state', async () => {
    let resolveList: ((value: { releases: Release[]; total: number; limit: number; offset: number }) => void) | undefined
    api.list.mockImplementation(() => new Promise(resolve => { resolveList = resolve }))

    render(<WhatsNewPage />)
    expect(screen.getByRole('status')).toHaveTextContent('Loading release notes')

    resolveList?.({ releases: [], total: 0, limit: RELEASE_PAGE_SIZE, offset: 0 })
    expect(await screen.findByText('No release notes have been published yet.')).toBeInTheDocument()
  })

  it('renders structured public fields without exposing PR or provenance metadata', async () => {
    api.list.mockResolvedValue({
      releases: [release({ source_pr_number: 1096, provenance_json: { importer: 'release-import-v1' } })],
      total: 1,
      limit: RELEASE_PAGE_SIZE,
      offset: 0,
    })

    render(<WhatsNewPage />)

    expect(await screen.findByText('Queue cards open details')).toBeInTheDocument()
    expect(screen.getByText('Queue')).toBeInTheDocument()
    expect(screen.getByText('Selecting a Queue card now opens its thread details reliably.')).toBeInTheDocument()
    expect(screen.queryByText(/1096/)).not.toBeInTheDocument()
    expect(screen.queryByText(/release-import-v1/)).not.toBeInTheDocument()
  })

  it('loads older releases incrementally using the current offset', async () => {
    api.list
      .mockResolvedValueOnce({
        releases: [release({ id: 2, title: 'Newest release' })],
        total: 2,
        limit: RELEASE_PAGE_SIZE,
        offset: 0,
      })
      .mockResolvedValueOnce({
        releases: [release({ id: 1, title: 'Older release', released_at: '2026-08-10T20:00:00Z' })],
        total: 2,
        limit: RELEASE_PAGE_SIZE,
        offset: 1,
      })

    render(<WhatsNewPage />)
    await screen.findByText('Newest release')

    fireEvent.click(screen.getByRole('button', { name: 'Load older updates' }))

    expect(await screen.findByText('Older release')).toBeInTheDocument()
    expect(api.list).toHaveBeenNthCalledWith(1, RELEASE_PAGE_SIZE, 0)
    expect(api.list).toHaveBeenNthCalledWith(2, RELEASE_PAGE_SIZE, 1)
    expect(screen.queryByRole('button', { name: 'Load older updates' })).not.toBeInTheDocument()
  })

  it('keeps retry behavior when the release API fails', async () => {
    api.list
      .mockRejectedValueOnce(new Error('release API unavailable'))
      .mockResolvedValueOnce({ releases: [], total: 0, limit: RELEASE_PAGE_SIZE, offset: 0 })

    render(<WhatsNewPage />)

    expect(await screen.findByRole('alert')).toHaveTextContent('release API unavailable')
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))

    await waitFor(() => expect(api.list).toHaveBeenCalledTimes(2))
    expect(await screen.findByText('No release notes have been published yet.')).toBeInTheDocument()
  })

  it('uses a safe fallback for non-Error API failures', async () => {
    api.list.mockRejectedValue('offline')
    render(<WhatsNewPage />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Release notes could not be loaded.')
  })
})
