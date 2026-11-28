import type { ReactNode } from 'react'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useRollBootstrap } from '../hooks/useRollBootstrap'
import { useRollPendingSelection } from '../hooks/useRollPendingSelection'
import { queryClient } from '../query/queryClient'
import { queryKeys } from '../query/queryKeys'
import { dependenciesApi } from '../services/api-dependencies'
import { rollResourcesApi } from '../services/rollResourcesApi'
import type { IssueCardsResponse } from '../generated/nativeV2Client'
import type { RollPendingSelection } from '../services/rollPendingSelection'
import type { RollLastReadPayload } from '../types'

vi.mock('../hooks/useRollPendingSelection', () => ({ useRollPendingSelection: vi.fn() }))
vi.mock('../services/rollResourcesApi', () => ({
  rollResourcesApi: {
    dieState: vi.fn(),
    eligibleIssueIds: vi.fn(),
    issueCards: vi.fn(),
  },
}))
vi.mock('../services/api-dependencies', () => ({
  dependenciesApi: { getIssueDependencies: vi.fn() },
}))

const mockedPending = vi.mocked(useRollPendingSelection)
const mockedResources = vi.mocked(rollResourcesApi)
const mockedDependencies = vi.mocked(dependenciesApi.getIssueDependencies)

type IssueCard = IssueCardsResponse['items'][number]

function card(issueId: number, threadId: number, status: string): IssueCard {
  return {
    issue_id: issueId,
    thread_id: threadId,
    thread_title: threadId === 3 ? 'Current Series' : 'Earlier Series',
    issue_number: String(issueId),
    has_confirmed_identity: false,
    mapping_state: 'unmapped',
    status,
  }
}

const LAST_READ: RollLastReadPayload = {
  issue_id: 10,
  issue_number: '10',
  thread_id: 3,
  thread_title: 'Current Series',
  read_at: '2026-11-28T00:00:00.000Z',
}

function wrapper() {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  }
}

describe('useRollBootstrap composed scoped view', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    queryClient.clear()
    mockedPending.mockReturnValue({
      pending: null,
      seedFromOffer: vi.fn(),
      select: vi.fn(),
      clear: vi.fn(),
      clearAll: vi.fn(),
    })
    mockedResources.dieState.mockResolvedValue({ die: 6, default_die: 6, ladder: [2, 4, 6, 8, 10, 12, 20] })
    mockedResources.eligibleIssueIds.mockResolvedValue({
      die: 6,
      issue_ids: [10],
      thread_ids: [3],
      pool_reason: 'ready',
    })
    mockedResources.issueCards.mockResolvedValue({ items: [card(10, 3, 'unread')] })
    mockedDependencies.mockResolvedValue({ issue_id: 10, incoming: [], outgoing: [] })
  })

  it('includes the committed rate last-read record in the composed view model', async () => {
    queryClient.setQueryData(queryKeys.roll.lastRead(), {
      roll_reconciliation: { last_read: LAST_READ },
    })

    const { result } = renderHook(() => useRollBootstrap(), { wrapper })
    await waitFor(() => expect(result.current.isPending).toBe(false))

    expect(result.current.data?.last_read).toEqual(LAST_READ)
    expect(result.current.data?.roll_pool).toHaveLength(1)
    expect(result.current.data?.roll_recovery).toBeNull()
    expect(result.current.data?.session_id).toBeUndefined()
  })

  it('uses the exact browser-owned pending selection as the active thread', async () => {
    const pending: RollPendingSelection = {
      issue_id: 10,
      thread_id: 3,
      issue_number: '10',
      result: 6,
      selected_at: 1_700_000_000_000,
    }
    mockedPending.mockReturnValue({
      pending,
      seedFromOffer: vi.fn(),
      select: vi.fn(),
      clear: vi.fn(),
      clearAll: vi.fn(),
    })

    const { result } = renderHook(() => useRollBootstrap(), { wrapper })
    await waitFor(() => expect(result.current.isPending).toBe(false))

    expect(result.current.data?.pending_thread_id).toBe(3)
    expect(result.current.data?.last_rolled_result).toBe(6)
    expect(result.current.data?.active_thread?.issue_id).toBe(10)
    expect(result.current.data?.roll_recovery).toBeNull()
  })

  it('wires owner-scoped recovery when the pending issue is blocked', async () => {
    const pending: RollPendingSelection = {
      issue_id: 10,
      thread_id: 3,
      issue_number: '10',
      selected_at: 1_700_000_000_000,
    }
    mockedPending.mockReturnValue({
      pending,
      seedFromOffer: vi.fn(),
      select: vi.fn(),
      clear: vi.fn(),
      clearAll: vi.fn(),
    })
    mockedResources.eligibleIssueIds.mockResolvedValue({
      issue_ids: [20],
      thread_ids: [4],
      pool_reason: 'ready',
    })
    mockedResources.issueCards.mockImplementation(async (ids: readonly number[]) => ({
      items: ids.includes(9) ? [card(9, 7, 'unread')] : [card(20, 4, 'unread')],
    }))
    mockedDependencies.mockResolvedValue({
      issue_id: 10,
      incoming: [{
        dependency_id: 55,
        source_issue_id: 9,
        source_issue_number: '3',
        source_thread_id: 7,
        source_thread_title: 'Earlier Series',
      }],
      outgoing: [],
    })

    const { result } = renderHook(() => useRollBootstrap(), { wrapper })
    await waitFor(() => expect(result.current.data?.roll_recovery).not.toBeNull())

    expect(mockedDependencies).toHaveBeenCalledWith(10)
    expect(result.current.data?.roll_recovery?.direct_blockers[0].source_id).toBe(9)
    expect(result.current.data?.roll_recovery?.readable_prerequisites[0].node_id).toBe(9)
  })

  it('stays empty while the scoped pool has no visible cards', async () => {
    mockedResources.eligibleIssueIds.mockResolvedValue({
      issue_ids: [],
      thread_ids: [],
      pool_reason: 'no_series',
    })

    const { result } = renderHook(() => useRollBootstrap(), { wrapper })
    await waitFor(() => expect(result.current.isPending).toBe(false))

    expect(result.current.data?.roll_pool).toEqual([])
    expect(result.current.data?.pool_reason).toBe('no_series')
    expect(result.current.data?.last_read).toBeNull()
  })
})
