import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  ISSUE_CARDS_BATCH_SIZE,
  useThreadIssueRatings,
} from '../hooks/useThreadIssueRatings'
import { issueCardsApi } from '../services/api-issue-cards'
import type { IssueCardsResponse } from '../generated/nativeV2Client'

vi.mock('../services/api-issue-cards', () => ({
  issueCardsApi: { cards: vi.fn() },
}))

const mockedCards = vi.mocked(issueCardsApi.cards)

function card(issue_id: number, rating: number | null) {
  return {
    issue_id,
    thread_id: 7,
    thread_title: 'Test Thread',
    issue_number: String(issue_id),
    status: 'read',
    read_at: rating == null ? null : '2026-11-04T18:30:00Z',
    rating,
    has_confirmed_identity: false,
    mapping_state: 'unmapped',
    comicvine_issue_id: null,
    cover_image_url: null,
  }
}

function cardsResponse(ratingById: Record<number, number | null>): IssueCardsResponse {
  return {
    items: Object.entries(ratingById).map(([issue_id, rating]) =>
      card(Number(issue_id), rating),
    ),
  }
}

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

describe('useThreadIssueRatings', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('fetches one bounded batch for the visible ids and returns rated rows', async () => {
    mockedCards.mockResolvedValue(cardsResponse({ 11: 4, 12: null, 13: 3.5 }))

    const { result } = renderHook(
      () => useThreadIssueRatings(7, [13, 11, 12, 11]),
      { wrapper },
    )

    await waitFor(() => expect(result.current.isPending).toBe(false))
    expect(mockedCards).toHaveBeenCalledTimes(1)
    expect(mockedCards).toHaveBeenCalledWith([11, 12, 13])
    expect(result.current.ratingsByIssueId.get(11)).toBe(4)
    expect(result.current.ratingsByIssueId.get(13)).toBe(3.5)
    expect(result.current.ratingsByIssueId.has(12)).toBe(false)
    expect(result.current.isError).toBe(false)
  })

  it('stays disabled until the issue section is expanded or ids exist', () => {
    const collapsed = renderHook(() => useThreadIssueRatings(7, [11], false), {
      wrapper,
    })
    expect(mockedCards).not.toHaveBeenCalled()
    expect(collapsed.result.current.ratingsByIssueId.size).toBe(0)
    collapsed.unmount()

    const empty = renderHook(() => useThreadIssueRatings(7, []), { wrapper })
    expect(mockedCards).not.toHaveBeenCalled()
    expect(empty.result.current.ratingsByIssueId.size).toBe(0)
    empty.unmount()

    const noThread = renderHook(() => useThreadIssueRatings(null, [11]), {
      wrapper,
    })
    expect(mockedCards).not.toHaveBeenCalled()
    expect(noThread.result.current.ratingsByIssueId.size).toBe(0)
  })

  it('splits large visible sets into bounded chunks within the card limit', async () => {
    const ids = Array.from({ length: ISSUE_CARDS_BATCH_SIZE + 50 }, (_, index) => index + 1)
    mockedCards.mockImplementation(async (requested: number[]) =>
      cardsResponse(Object.fromEntries(requested.map((id) => [id, 4]))),
    )

    const { result } = renderHook(() => useThreadIssueRatings(7, ids), {
      wrapper,
    })

    await waitFor(() => expect(result.current.isPending).toBe(false))
    expect(mockedCards).toHaveBeenCalledTimes(2)
    const requestedSizes = mockedCards.mock.calls.map((call) => call[0].length)
    expect(requestedSizes.every((size) => size <= ISSUE_CARDS_BATCH_SIZE)).toBe(true)
    expect(result.current.ratingsByIssueId.size).toBe(ids.length)
    expect(result.current.ratingsByIssueId.get(1)).toBe(4)
    expect(result.current.ratingsByIssueId.get(ids.length)).toBe(4)
  })

  it('degrades to an empty map when the cards read fails', async () => {
    mockedCards.mockRejectedValue(new Error('cards unavailable'))

    const { result } = renderHook(() => useThreadIssueRatings(7, [11, 12]), {
      wrapper,
    })

    await waitFor(() => expect(result.current.isPending).toBe(false))
    expect(result.current.isError).toBe(true)
    expect(result.current.ratingsByIssueId.size).toBe(0)
  })
})
