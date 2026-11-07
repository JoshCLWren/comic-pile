import { describe, expect, it, vi } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useRollResourceSnapshot } from '../hooks/useRollResources'
import type { RollResourcesApi } from '../services/rollResourcesApi'

function wrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
}

function api(): RollResourcesApi {
  return {
    dieState: vi.fn(async () => ({ die: 20, ladder: [2, 4, 6, 8, 10, 12, 20], default_die: 20, last_roll: null })),
    eligibleIssueIds: vi.fn(async () => ({ die: 20, issue_ids: [101, 102], thread_ids: [1, 2] })),
    issueCards: vi.fn(async () => ({ items: [] })),
  } as RollResourcesApi
}

describe('useRollResourceSnapshot', () => {
  it('composes die, eligible ids and cards without a URL surface', async () => {
    const fake = api()
    const { result } = renderHook(() => useRollResourceSnapshot([], fake), { wrapper: wrapper() })
    await act(async () => { await new Promise((r) => setTimeout(r, 0)) })
    expect(result.current.dieState?.die).toBe(20)
    expect(result.current.eligibleIssueIds?.issue_ids).toEqual([101, 102])
    expect(fake.issueCards).toHaveBeenCalledWith([101, 102])
    expect(result.current.isError).toBe(false)
  })
})
