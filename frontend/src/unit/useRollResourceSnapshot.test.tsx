import { describe, expect, it, vi } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useRollIssueCards, useRollResourceSnapshot } from '../hooks/useRollResources'
import type {
  DieStateResponse,
  EligibleIssueIdsResponse,
  IssueCardsResponse,
  RollResourcesApi,
} from '../services/rollResourcesApi'

function wrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
}

function api(eligible: number[] = [101, 102]): RollResourcesApi {
  return {
    dieState: vi.fn(
      async (): Promise<DieStateResponse> => ({
        die: 20,
        ladder: [2, 4, 6, 8, 10, 12, 20],
        default_die: 20,
        last_roll: null,
      }),
    ),
    eligibleIssueIds: vi.fn(
      async (): Promise<EligibleIssueIdsResponse> => ({
        die: 20,
        issue_ids: eligible,
        thread_ids: eligible.map((_, index) => index + 1),
        pool_reason: eligible.length > 0 ? 'ready' : 'no_series',
      }),
    ),
    issueCards: vi.fn(async (): Promise<IssueCardsResponse> => ({ items: [] })),
  }
}

describe('useRollResourceSnapshot', () => {
  it('composes die, eligible ids and cards without a URL surface', async () => {
    const fake = api()
    const { result } = renderHook(() => useRollResourceSnapshot([], fake), { wrapper: wrapper() })
    await waitFor(() => expect(result.current.dieState?.die).toBe(20))
    expect(result.current.eligibleIssueIds?.issue_ids).toEqual([101, 102])
    await waitFor(() => expect(fake.issueCards).toHaveBeenCalledWith([101, 102]))
    expect(result.current.isError).toBe(false)
  })

  it('does not refetch an empty card batch', async () => {
    const fake = api([])
    const { result } = renderHook(() => useRollResourceSnapshot([], fake), { wrapper: wrapper() })
    await waitFor(() =>
      expect(result.current.eligibleIssueIds).toEqual({
        die: 20,
        issue_ids: [],
        thread_ids: [],
        pool_reason: 'no_series',
      }),
    )

    await act(async () => {
      await result.current.refetch()
    })

    expect(fake.issueCards).not.toHaveBeenCalled()
  })
})

function issueCard(id: number): IssueCardsResponse['items'][number] {
  return {
    issue_id: id,
    thread_id: id,
    thread_title: `Series ${id}`,
    issue_number: '1',
    status: 'unread',
    has_confirmed_identity: true,
    mapping_state: 'confirmed',
    cover_image_url: `https://covers.example.test/${id}.jpg`,
  }
}

describe('useRollIssueCards cover stability (#5566)', () => {
  it('keeps a matching cover while the next eligible batch loads', async () => {
    let resolveNext!: (cards: IssueCardsResponse) => void
    const nextBatch = new Promise<IssueCardsResponse>((resolve) => {
      resolveNext = resolve
    })
    const fake = api()
    fake.issueCards = vi.fn((ids: readonly number[]) =>
      ids.length === 1 && ids[0] === 101
        ? Promise.resolve({ items: [issueCard(101)] })
        : nextBatch,
    )

    const { result, rerender } = renderHook(
      ({ ids }: { ids: number[] }) => useRollIssueCards(ids, fake),
      { initialProps: { ids: [101] }, wrapper: wrapper() },
    )
    await waitFor(() =>
      expect(result.current.data?.items[0]?.cover_image_url).toBe('https://covers.example.test/101.jpg'),
    )

    // Rolling changes the scoped batch before its next fetch has completed.
    // An unchanged issue must not briefly render a missing/black cover.
    rerender({ ids: [101, 102] })
    await waitFor(() => expect(fake.issueCards).toHaveBeenCalledWith([101, 102]))
    expect(result.current.data?.items.map((card) => card.issue_id)).toEqual([101])
    expect(result.current.data?.items[0]?.cover_image_url).toBe('https://covers.example.test/101.jpg')

    await act(async () => {
      resolveNext({ items: [issueCard(101), issueCard(102)] })
    })
    await waitFor(() => expect(result.current.data?.items.map((card) => card.issue_id)).toEqual([101, 102]))
  })

  it('does not display an old cover for a different issue id', async () => {
    let resolveNext!: (cards: IssueCardsResponse) => void
    const nextBatch = new Promise<IssueCardsResponse>((resolve) => {
      resolveNext = resolve
    })
    const fake = api()
    fake.issueCards = vi.fn((ids: readonly number[]) =>
      ids[0] === 101
        ? Promise.resolve({ items: [issueCard(101)] })
        : nextBatch,
    )
    const { result, rerender } = renderHook(
      ({ ids }: { ids: number[] }) => useRollIssueCards(ids, fake),
      { initialProps: { ids: [101] }, wrapper: wrapper() },
    )
    await waitFor(() => expect(result.current.data?.items[0]?.issue_id).toBe(101))

    rerender({ ids: [102] })
    await waitFor(() => expect(fake.issueCards).toHaveBeenCalledWith([102]))
    expect(result.current.data?.items).toEqual([])

    await act(async () => {
      resolveNext({ items: [issueCard(102)] })
    })
    await waitFor(() => expect(result.current.data?.items[0]?.issue_id).toBe(102))
  })
})
