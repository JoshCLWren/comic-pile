import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import WhatsNewPage, {
  groupReleasesByDay,
  releaseDisplayText,
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
    released_at: '2026-08-11T20:00:00Z',
    category: 'Queue',
    title: 'Queue cards open details',
    summary: 'Selecting a Queue card now opens its thread details reliably.',
    body: null,
    sort_order: 0,
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

  it('falls back to release id when timestamps and sort order are identical', () => {
    expect(sortReleasesNewestFirst([
      release({ id: 4, sort_order: 7 }),
      release({ id: 9, sort_order: 7 }),
    ]).map(item => item.id)).toEqual([9, 4])
  })

  it('pushes malformed historical timestamps behind valid release dates', () => {
    expect(sortReleasesNewestFirst([
      release({ id: 1, released_at: 'not-a-date' }),
      release({ id: 2, released_at: '2026-08-10T20:00:00Z' }),
    ]).map(item => item.id)).toEqual([2, 1])
  })

  it('groups historical and PR-backed releases by localized release day', () => {
    const days = groupReleasesByDay([
      release({ id: 3, released_at: '2026-08-11T20:00:00Z' }),
      release({ id: 2, released_at: '2026-08-11T10:00:00Z' }),
      release({ id: 1, released_at: '2026-08-10T20:00:00Z' }),
    ], 'UTC')

    expect(days).toHaveLength(2)
    expect(days[0].releases.map(item => item.id)).toEqual([3, 2])
    expect(days[1].releases.map(item => item.id)).toEqual([1])
  })

  it('keeps malformed historical timestamps in an explicit unknown-date group', () => {
    const days = groupReleasesByDay([
      release({ id: 2, released_at: '2026-08-10T20:00:00Z' }),
      release({ id: 1, released_at: 'not-a-date' }),
    ], 'UTC')

    expect(days.map(day => day.key)).toEqual(['2026-08-10', 'unknown'])
    expect(days[1].label).toBe('Unknown date')
    expect(days[1].releases.map(item => item.id)).toEqual([1])
  })
})

describe('releaseDisplayText', () => {
  it('keeps the label of well-formed GitHub markdown links', () => {
    expect(releaseDisplayText('[#1058](https://github.com/JoshCLWren/comic-pile/pull/1058)')).toBe('#1058')
  })

  it('removes GitHub URLs truncated by the release title column limit', () => {
    expect(
      releaseDisplayText('cache-update behavior ([#820](https://github.com/JoshCLWren/comic-pile/pull/820), [#823](https://github.com/JoshCLWren/comic-pi'),
    ).toBe('cache-update behavior (#820, #823')
  })

  it('removes bare GitHub URLs embedded in prose', () => {
    expect(
      releaseDisplayText('see https://github.com/JoshCLWren/comic-pile/pull/823 for details').includes('github.com'),
    ).toBe(false)
  })

  it('removes backticked and URL-as-label GitHub links', () => {
    expect(releaseDisplayText('`https://github.com/JoshCLWren/comic-pile/pull/823`')).toBe('')
    expect(
      releaseDisplayText('[https://github.com/JoshCLWren/comic-pile/pull/823](https://github.com/JoshCLWren/comic-pile/pull/823)'),
    ).toBe('')
  })

  it('keeps labels for non-GitHub markdown links and strips backticks', () => {
    expect(releaseDisplayText('[docs](https://example.com/readme)')).toBe('docs')
    expect(releaseDisplayText('`PROD_BASE_URL` now defaults to `https://comic-pile.vercel.app`.')).toBe(
      'PROD_BASE_URL now defaults to https://comic-pile.vercel.app.',
    )
  })

  it('treats www and subdomain GitHub hostnames as GitHub links', () => {
    expect(releaseDisplayText('[x](https://www.github.com/foo)')).toBe('x')
    expect(releaseDisplayText('[x](https://gist.github.com/abc)')).toBe('x')
    expect(releaseDisplayText('x https://github.com./a')).toBe('x')
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
      releases: [release({ id: 10 })],
      total: 1,
      limit: RELEASE_PAGE_SIZE,
      offset: 0,
    })

    render(<WhatsNewPage />)

    expect(await screen.findByText('Queue cards open details')).toBeInTheDocument()
    expect(screen.getByText('Queue')).toBeInTheDocument()
    expect(screen.getByText('Selecting a Queue card now opens its thread details reliably.')).toBeInTheDocument()
    expect(screen.getByText('1 update published this day.')).toBeInTheDocument()
    expect(screen.queryByText(/1096/)).not.toBeInTheDocument()
    expect(screen.queryByText(/release-import-v1/)).not.toBeInTheDocument()
  })

  it('never renders GitHub links from release titles or summaries', async () => {
    api.list.mockResolvedValue({
      releases: [
        release({
          id: 7,
          title: 'Dependency groups ([#790](https://github.com/JoshCLWren/comic-pile/pull/790), [#805](https://github.com/JoshCLWren/comic-pi',
          summary: 'Dependency groups (#790, #805, #807).',
        }),
      ],
      total: 1,
      limit: RELEASE_PAGE_SIZE,
      offset: 0,
    })

    render(<WhatsNewPage />)

    expect(await screen.findByText('Dependency groups (#790, #805')).toBeInTheDocument()
    expect(screen.queryByText(/github\.com/i)).not.toBeInTheDocument()
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
  })

  it('renders the plural day summary for multiple same-day releases', async () => {
    api.list.mockResolvedValue({
      releases: [
        release({ id: 2, title: 'First same-day update' }),
        release({ id: 1, title: 'Second same-day update' }),
      ],
      total: 2,
      limit: RELEASE_PAGE_SIZE,
      offset: 0,
    })

    render(<WhatsNewPage />)

    expect(await screen.findByText('First same-day update')).toBeInTheDocument()
    expect(screen.getByText('2 updates published this day.')).toBeInTheDocument()
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

  it('shows a pending label while an older release page is loading', async () => {
    let resolveOlder: ((value: { releases: Release[]; total: number; limit: number; offset: number }) => void) | undefined
    api.list
      .mockResolvedValueOnce({
        releases: [release({ id: 2, title: 'Newest release' })],
        total: 2,
        limit: RELEASE_PAGE_SIZE,
        offset: 0,
      })
      .mockImplementationOnce(() => new Promise(resolve => { resolveOlder = resolve }))

    render(<WhatsNewPage />)
    await screen.findByText('Newest release')

    fireEvent.click(screen.getByRole('button', { name: 'Load older updates' }))
    expect(await screen.findByRole('button', { name: 'Loading older updates…' })).toBeDisabled()

    resolveOlder?.({
      releases: [release({ id: 1, title: 'Older release', released_at: '2026-08-10T20:00:00Z' })],
      total: 2,
      limit: RELEASE_PAGE_SIZE,
      offset: 1,
    })
    expect(await screen.findByText('Older release')).toBeInTheDocument()
  })

  it('retries the exact failed pagination request instead of restarting history', async () => {
    api.list
      .mockResolvedValueOnce({
        releases: [release({ id: 2, title: 'Newest release' })],
        total: 2,
        limit: RELEASE_PAGE_SIZE,
        offset: 0,
      })
      .mockRejectedValueOnce(new Error('older page unavailable'))
      .mockResolvedValueOnce({
        releases: [release({ id: 1, title: 'Recovered older release', released_at: '2026-08-10T20:00:00Z' })],
        total: 2,
        limit: RELEASE_PAGE_SIZE,
        offset: 1,
      })

    render(<WhatsNewPage />)
    await screen.findByText('Newest release')
    fireEvent.click(screen.getByRole('button', { name: 'Load older updates' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('older page unavailable')

    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))

    expect(await screen.findByText('Recovered older release')).toBeInTheDocument()
    expect(api.list).toHaveBeenNthCalledWith(2, RELEASE_PAGE_SIZE, 1)
    expect(api.list).toHaveBeenNthCalledWith(3, RELEASE_PAGE_SIZE, 1)
  })

  it('keeps retry behavior when the initial release API request fails', async () => {
    api.list
      .mockRejectedValueOnce(new Error('release API unavailable'))
      .mockResolvedValueOnce({ releases: [], total: 0, limit: RELEASE_PAGE_SIZE, offset: 0 })

    render(<WhatsNewPage />)

    expect(await screen.findByRole('alert')).toHaveTextContent('release API unavailable')
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))

    await waitFor(() => expect(api.list).toHaveBeenCalledTimes(2))
    expect(api.list).toHaveBeenNthCalledWith(2, RELEASE_PAGE_SIZE, 0)
    expect(await screen.findByText('No release notes have been published yet.')).toBeInTheDocument()
  })

  it('uses a safe fallback for non-Error API failures', async () => {
    api.list.mockRejectedValue('offline')
    render(<WhatsNewPage />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Release notes could not be loaded.')
  })
})
