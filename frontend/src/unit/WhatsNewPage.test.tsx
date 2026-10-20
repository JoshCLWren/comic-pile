import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import WhatsNewPage, {
  decodeReleaseEscapes,
  groupReleasesByDay,
  hasUnfinishedWorkMarkers,
  isDisplayableRelease,
  releaseDisplayText,
  releaseTimeLabel,
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

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
  return render(<WhatsNewPage />, { wrapper: Wrapper })
}

function release(overrides: Partial<Release> = {}): Release {
  // SAFETY: the release fixture supplies only the fields the changelog list reads
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

    it('resolves Markdown formatting without re-implementing backend repair', () => {
      expect(releaseDisplayText(
        '[Fix queue](https://github.com/JoshCLWren/comic-pile/pull/1058) persists reading lists',
      )).toBe('Fix queue persists reading lists')
      expect(releaseDisplayText(
        'https://github.com/JoshCLWren/comic-pile/pull/1058 persists reading lists',
      )).toBe('persists reading lists')
      expect(releaseDisplayText('`queue` search')).toBe('queue search')
    })

    it('renders copy the public API already repaired without changing it', () => {
      expect(releaseDisplayText('Queue cards open details')).toBe('Queue cards open details')
      expect(releaseDisplayText(
        'Your saved filter now survives a page reload.',
      )).toBe('Your saved filter now survives a page reload.')
    })

    it('decodes escaped apostrophes without corrupting legitimate backslashes', () => {
      expect(releaseDisplayText('GitHub links added to What\\u0027s New page')).toBe(
        "GitHub links added to What's New page",
      )
      expect(releaseDisplayText("the Roll page\\'s rating view")).toBe(
        "the Roll page's rating view",
      )
      expect(decodeReleaseEscapes('What\\\\u0027s New page')).toBe(
        "What's New page",
      )
      expect(decodeReleaseEscapes('The What\\u2019s New page')).toBe(
        'The What\u2019s New page',
      )
      expect(releaseDisplayText('Open C:\\Users\\reader\\notes')).toBe(
        'Open C:\\Users\\reader\\notes',
      )
      expect(releaseDisplayText('Match \\d+ rows in your reading log')).toBe(
        'Match \\d+ rows in your reading log',
      )
    })

    it('flags unfinished-work commentary for omission', () => {
      expect(hasUnfinishedWorkMarkers(release({ title: 'incomplete #1551 fix' }))).toBe(true)
      expect(hasUnfinishedWorkMarkers(release({ summary: 'TODO: finish the rollout' }))).toBe(true)
      expect(hasUnfinishedWorkMarkers(release({ title: 'Queue cards open details' }))).toBe(false)
    })

    it('hides entries whose copy is only a low-information internal fragment', () => {
      expect(isDisplayableRelease(release({ id: 1, title: 'loading states', summary: 'loading states' }))).toBe(false)
      expect(isDisplayableRelease(release({ id: 2, title: 'wip' }))).toBe(false)
    })

    it('keeps useful historical entries that already meet the reader-facing contract', () => {
      expect(isDisplayableRelease(release({
        id: 3,
        title: 'Reading queue remembers your place',
        summary: 'Reopening a comic now resumes on the exact page you left.',
      }))).toBe(true)
    })

    it('hides placeholder-sized titles from the public page', () => {
      expect(isDisplayableRelease(release({ id: 1, title: 'T' }))).toBe(false)
      expect(isDisplayableRelease(release({ id: 2, title: 'S' }))).toBe(false)
      expect(isDisplayableRelease(release({ id: 3, title: 'Add queue search' }))).toBe(true)
    })
  })

describe('release time-of-day formatting', () => {
    it('formats the release time-of-day for the requested timezone', () => {
      expect(releaseTimeLabel('2026-08-11T20:30:00Z', 'UTC')).toMatch(/^\d{1,2}:\d{2}/)
      expect(releaseTimeLabel('2026-08-11T20:30:00Z', 'UTC')).not.toBe(
        releaseTimeLabel('2026-08-11T21:30:00Z', 'UTC'),
      )
    })

    it('hides the published-time line when the timestamp is malformed', () => {
      expect(releaseTimeLabel('not-a-date')).toBe('')
    })

    it('renders the local published time-of-day on each card', async () => {
      api.list.mockResolvedValue({
        releases: [release({ id: 11, title: 'Timed release note' })],
        total: 1,
        limit: RELEASE_PAGE_SIZE,
        offset: 0,
      })

      renderPage()

      expect(await screen.findByText('Timed release note')).toBeInTheDocument()
      expect(screen.getByText(/Published at \d{1,2}:\d{2}/)).toBeInTheDocument()
    })
  })

describe('WhatsNewPage', () => {
    it('shows loading and then the empty release-ledger state', async () => {
      let resolveList: ((value: { releases: Release[]; total: number; limit: number; offset: number }) => void) | undefined
      api.list.mockImplementation(() => new Promise(resolve => { resolveList = resolve }))

      renderPage()
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

      renderPage()

      expect(await screen.findByText('Queue cards open details')).toBeInTheDocument()
      expect(screen.getByText('Queue')).toBeInTheDocument()
      expect(screen.getByText('Selecting a Queue card now opens its thread details reliably.')).toBeInTheDocument()
      expect(screen.getByText('1 update published this day.')).toBeInTheDocument()
      expect(screen.queryByText(/1096/)).not.toBeInTheDocument()
      expect(screen.queryByText(/release-import-v1/)).not.toBeInTheDocument()
      expect(screen.queryByText(/github\.com/)).not.toBeInTheDocument()
    })

    it('renders decoded apostrophes in card titles and summaries', async () => {
      api.list.mockResolvedValue({
        releases: [
          release({
            id: 12,
            title: 'GitHub links added to What\\u0027s New page',
            summary: "The Roll page\\'s rating view now remembers your place.",
          }),
        ],
        total: 1,
        limit: RELEASE_PAGE_SIZE,
        offset: 0,
      })

      renderPage()

      expect(
        await screen.findByText("GitHub links added to What's New page"),
      ).toBeInTheDocument()
      expect(
        screen.getByText("The Roll page's rating view now remembers your place."),
      ).toBeInTheDocument()
      expect(screen.queryByText(/\\u0027/)).not.toBeInTheDocument()
      expect(screen.queryByText(/\\'s/)).not.toBeInTheDocument()
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

      renderPage()

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

      renderPage()
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

      renderPage()
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

      renderPage()
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

      renderPage()

      expect(await screen.findByRole('alert')).toHaveTextContent('release API unavailable')
      fireEvent.click(screen.getByRole('button', { name: 'Try again' }))

      await waitFor(() => expect(api.list).toHaveBeenCalledTimes(2))
      expect(api.list).toHaveBeenNthCalledWith(2, RELEASE_PAGE_SIZE, 0)
      expect(await screen.findByText('No release notes have been published yet.')).toBeInTheDocument()
    })

    it('uses a safe fallback for non-Error API failures', async () => {
      api.list.mockRejectedValue('offline')
      renderPage()
      expect(await screen.findByRole('alert')).toHaveTextContent('Release notes could not be loaded.')
    })

    it('skips placeholder-sized releases so broken entries never reach the page', async () => {
      api.list.mockResolvedValue({
        releases: [
          release({ id: 2, title: 'T', summary: 'S', category: 'bug' }),
          release({ id: 1, title: 'Real release note' }),
        ],
        total: 2,
        limit: RELEASE_PAGE_SIZE,
        offset: 0,
      })

      renderPage()

      expect(await screen.findByText('Real release note')).toBeInTheDocument()
      expect(screen.queryByText('T')).not.toBeInTheDocument()
      expect(screen.queryByText('S')).not.toBeInTheDocument()
      expect(screen.getByText('1 update published this day.')).toBeInTheDocument()
    })

    it('omits internal-artifact entries so ticket numbers, schema identifiers, and unfinished-work notes never render', async () => {
      api.list.mockResolvedValue({
        releases: [
          release({
            id: 1,
            title: 'Real reader update',
            summary: 'Your pile now syncs instantly across devices.',
          }),
          release({
            id: 2,
            title: 'incomplete #1551 fix',
            summary: 'Added source_roll_event_id instrumentation for Phase 2 and 3.',
          }),
          release({
            id: 3,
            title: 'loading states',
            summary: 'loading states',
          }),
        ],
        total: 3,
        limit: RELEASE_PAGE_SIZE,
        offset: 0,
      })

      renderPage()

      expect(await screen.findByText('Real reader update')).toBeInTheDocument()
      expect(screen.queryByText(/incomplete/i)).not.toBeInTheDocument()
      expect(screen.queryByText(/1551/)).not.toBeInTheDocument()
      expect(screen.queryByText(/source_roll_event_id/)).not.toBeInTheDocument()
      expect(screen.queryByText(/Phase 2 and 3/i)).not.toBeInTheDocument()
      expect(screen.queryByText('loading states')).not.toBeInTheDocument()
      expect(screen.getByText('1 update published this day.')).toBeInTheDocument()
    })

    it('renders server-repaired historical copy without re-sanitizing it', async () => {
      api.list.mockResolvedValue({
        releases: [
          release({
            id: 4,
            title: 'Roll recovery resumes interrupted sessions',
            summary: 'Interrupted rolls now continue where you left off instead of restarting.',
          }),
        ],
        total: 1,
        limit: RELEASE_PAGE_SIZE,
        offset: 0,
      })

      renderPage()

      expect(
        await screen.findByText('Roll recovery resumes interrupted sessions'),
      ).toBeInTheDocument()
      expect(screen.queryByText(/1886/)).not.toBeInTheDocument()
    })

    it('strips bare GitHub URLs from release titles and summaries', async () => {
      api.list.mockResolvedValue({
        releases: [
          release({
            id: 3,
            title: 'Fix https://github.com/JoshCLWren/comic-pile/issues/1110 roll bug',
            summary: 'See https://github.com/JoshCLWren/comic-pile/pull/1234 for details.',
          }),
        ],
        total: 1,
        limit: RELEASE_PAGE_SIZE,
        offset: 0,
      })

      renderPage()

      expect(await screen.findByText('Fix roll bug')).toBeInTheDocument()
      expect(screen.getByText('See for details.')).toBeInTheDocument()
      expect(screen.queryByText(/github\.com/)).not.toBeInTheDocument()
    })
  })
