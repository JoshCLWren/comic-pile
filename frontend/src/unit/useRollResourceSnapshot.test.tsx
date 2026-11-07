import { describe, expect, it, vi } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useRollResourceSnapshot } from '../hooks/useRollResources'
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
      expect(result.current.eligibleIssueIds).toEqual({ die: 20, issue_ids: [], thread_ids: [] }),
    )

    await act(async () => {
      await result.current.refetch()
    })

    expect(fake.issueCards).not.toHaveBeenCalled()
  })
})
