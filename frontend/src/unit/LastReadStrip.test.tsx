import { act, render, renderHook, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useRollLastRead, type RollLastReadView } from '../hooks/useRollLastRead'
import { LastReadStrip } from '../pages/RollPage/components/LastReadStrip'
import { queryClient } from '../query/queryClient'
import { queryKeys } from '../query/queryKeys'
import type { RateResponsePayload } from '../types'
import type { ReaderContextResponse } from '../services/api-reader-context'
import type { ComicVineIssueIntelligence } from '../services/api-comicvine'

const ISSUE_ID = 31
const THREAD_ID = 7

function rateResponse(overrides: Partial<RateResponsePayload> = {}): RateResponsePayload {
  return {
    id: THREAD_ID,
    title: 'Saga',
    format: 'Comic',
    issues_remaining: 3,
    total_issues: 12,
    queue_position: 1,
    status: 'active',
    is_blocked: false,
    blocking_reasons: [],
    last_activity_at: '2026-08-03T18:30:00Z',
    last_rating: 4,
    notes: null,
    is_test: false,
    created_at: '2026-08-03T00:00:00Z',
    roll_reconciliation: {
      last_read: {
        issue_id: ISSUE_ID,
        issue_number: '5',
        read_at: '2026-08-03T18:30:00Z',
        thread_id: THREAD_ID,
        thread_title: 'Saga',
      },
    },
    ...overrides,
  }
}

function readerContext(
  overrides: Partial<ReaderContextResponse['series']> = {},
): ReaderContextResponse {
  return {
    issue_id: ISSUE_ID,
    series: {
      identity_source: 'comicvine',
      canonical_series_id: 'cv-1',
      series_name: 'Saga',
      average_rating: 3.5,
      ratings_count: 2,
      previous_issue: null,
      recent_ratings: [],
      highest_rating: 4,
      lowest_rating: 3,
      ...overrides,
    },
    crossovers: [],
    local_chain: { issues: [], edges: [] },
  }
}

function intelligence(imageUrl: string | null = 'https://example.test/saga-5.jpg'): ComicVineIssueIntelligence {
  return {
    comicvine_issue_id: 'cv-issue-31',
    comicvine_url: null,
    series_name: 'Saga',
    series_id: 1,
    issue_number: '5',
    name: 'Chapter Five',
    description: null,
    image_url: imageUrl,
    cover_date: null,
    store_date: null,
    creators: [],
    story_arcs: [],
  }
}

function seedCaches(rate: RateResponsePayload, context: ReaderContextResponse, cover = intelligence()) {
  queryClient.setQueryData(queryKeys.roll.lastRead(), rate)
  queryClient.setQueryData(queryKeys.comicVine.issueIntelligence(ISSUE_ID), cover)
  queryClient.setQueryData(queryKeys.readerContext.detail(ISSUE_ID), context)
}

const view: RollLastReadView = {
  lastRead: {
    issue_id: ISSUE_ID,
    issue_number: '5',
    read_at: '2026-08-03T18:30:00Z',
    thread_id: THREAD_ID,
    thread_title: 'Saga',
  },
  rating: 4,
  issuesRemaining: 3,
  totalIssues: 12,
  coverUrl: 'https://example.test/saga-5.jpg',
  seriesStats: {
    averageRating: 3.5,
    ratingCount: 2,
    readCount: null,
    issueCount: null,
    scope: 'canonical_series_run',
  },
}

beforeEach(() => {
  vi.restoreAllMocks()
})

describe('useRollLastRead cache-only projection', () => {
  it('renders the saved rating and updated canonical stats from caches without a request', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch')
    seedCaches(rateResponse(), readerContext())

    const { result } = renderHook(() => useRollLastRead())

    expect(result.current?.lastRead.issue_number).toBe('5')
    expect(result.current?.rating).toBe(4)
    expect(result.current?.issuesRemaining).toBe(3)
    expect(result.current?.totalIssues).toBe(12)
    expect(result.current?.coverUrl).toBe('https://example.test/saga-5.jpg')
    expect(result.current?.seriesStats).toMatchObject({
      averageRating: 3.5,
      ratingCount: 2,
      scope: 'canonical_series_run',
    })
    expect(fetchSpy).not.toHaveBeenCalled()
    expect(queryClient.getQueryState(queryKeys.readerContext.detail(ISSUE_ID))?.fetchStatus).toBe(
      'idle',
    )
  })

  it('replaces the projection when a later rating commits a new average', async () => {
    seedCaches(rateResponse(), readerContext())
    const { result } = renderHook(() => useRollLastRead())

    expect(result.current?.seriesStats?.averageRating).toBe(3.5)

    act(() => {
      queryClient.setQueryData(
        queryKeys.roll.lastRead(),
        rateResponse({
          last_rating: 5,
          roll_reconciliation: {
            last_read: {
              issue_id: 32,
              issue_number: '6',
              read_at: '2026-08-04T10:00:00Z',
              thread_id: THREAD_ID,
              thread_title: 'Saga',
            },
          },
        }),
      )
      queryClient.setQueryData(
        queryKeys.readerContext.detail(32),
        readerContext({ average_rating: 4, ratings_count: 3 }),
      )
    })

    await waitFor(() => expect(result.current?.lastRead.issue_number).toBe('6'))
    expect(result.current?.rating).toBe(5)
    expect(result.current?.seriesStats).toMatchObject({ averageRating: 4, ratingCount: 3 })
  })

  it('yields no canonical stats when canonical identity is unresolved', () => {
    seedCaches(rateResponse(), readerContext({ identity_source: 'unavailable' }))

    const { result } = renderHook(() => useRollLastRead())

    expect(result.current?.seriesStats).toBeNull()
  })

  it('returns null when no last-read record is cached', () => {
    const { result } = renderHook(() => useRollLastRead())

    expect(result.current).toBeNull()
  })
})

describe('LastReadStrip', () => {
  it('shows identity, saved rating, canonical average, and run progress', () => {
    render(
      <LastReadStrip view={view} onDismiss={vi.fn()} onRollAgain={vi.fn()} />,
    )

    const strip = screen.getByTestId('last-read-strip')
    expect(strip).toHaveTextContent('Saga')
    expect(strip).toHaveTextContent('5')
    expect(strip).toHaveTextContent('Saved rating 4/5')
    expect(strip).toHaveTextContent('Series average 3.5/5 · 2 ratings')
    expect(strip).toHaveTextContent('9 of 12 issues read')
    expect(screen.getByRole('img', { name: 'Saga 5 cover' })).toHaveAttribute(
      'src',
      'https://example.test/saga-5.jpg',
    )
  })

  it('copies the title and issue string', async () => {
    const user = userEvent.setup()
    const writeText = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue(undefined)

    render(<LastReadStrip view={view} onDismiss={vi.fn()} onRollAgain={vi.fn()} />)

    await user.click(screen.getByRole('button', { name: 'Copy Saga 5' }))

    expect(writeText).toHaveBeenCalledWith('Saga 5')
    expect(screen.getByText('Copied')).toBeInTheDocument()
  })

  it('dismisses locally and rolls again through the page handlers', async () => {
    const user = userEvent.setup()
    const onDismiss = vi.fn()
    const onRollAgain = vi.fn()

    render(<LastReadStrip view={view} onDismiss={onDismiss} onRollAgain={onRollAgain} />)

    await user.click(screen.getByRole('button', { name: 'Dismiss last read' }))
    await user.click(screen.getByRole('button', { name: 'Roll again' }))

    expect(onDismiss).toHaveBeenCalledOnce()
    expect(onRollAgain).toHaveBeenCalledOnce()
  })

  it('renders a clean placeholder when the cover is missing', () => {
    render(
      <LastReadStrip
        view={{ ...view, coverUrl: null }}
        onDismiss={vi.fn()}
        onRollAgain={vi.fn()}
      />,
    )

    expect(screen.queryByRole('img', { name: 'Saga 5 cover' })).not.toBeInTheDocument()
    expect(screen.getByLabelText('Cover unavailable')).toBeInTheDocument()
  })

  it('omits canonical stats and run progress when they are unknown', () => {
    render(
      <LastReadStrip
        view={{
          ...view,
          totalIssues: null,
          issuesRemaining: null,
          seriesStats: null,
          rating: null,
        }}
        onDismiss={vi.fn()}
        onRollAgain={vi.fn()}
      />,
    )

    const strip = screen.getByTestId('last-read-strip')
    expect(strip).not.toHaveTextContent('Series average')
    expect(strip).not.toHaveTextContent('issues read')
    expect(strip).not.toHaveTextContent('Saved rating')
  })

  it('exposes undo only when the page says the rating can be reversed', async () => {
    const user = userEvent.setup()
    const onUndo = vi.fn()

    render(
      <LastReadStrip
        view={view}
        onDismiss={vi.fn()}
        onRollAgain={vi.fn()}
        onUndo={onUndo}
        canUndo
      />,
    )

    await user.click(screen.getByRole('button', { name: 'Undo this rating' }))

    expect(onUndo).toHaveBeenCalledOnce()
  })
})
