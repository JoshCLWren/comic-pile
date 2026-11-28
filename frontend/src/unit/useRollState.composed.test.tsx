import type { ReactNode } from 'react'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useRollState } from '../hooks/useRollState'
import { useRollPendingSelection } from '../hooks/useRollPendingSelection'
import { queryClient } from '../query/queryClient'
import { queryKeys } from '../query/queryKeys'
import { readRollSnoozes } from '../services/api-roll'
import { threadsApi } from '../services/api-threads'
import { rollResourcesApi } from '../services/rollResourcesApi'
import type { IssueCardsResponse } from '../generated/nativeV2Client'
import type { RollPendingSelection } from '../services/rollPendingSelection'
import type { RollLastReadPayload } from '../types'

vi.mock('../hooks/useRollPendingSelection', () => ({ useRollPendingSelection: vi.fn() }))
vi.mock('../services/rollResourcesApi', () => ({
  rollResourcesApi: {
    dieState: vi.fn(),
    lastRead: vi.fn(),
    eligibleIssueIds: vi.fn(),
    issueCards: vi.fn(),
    recovery: vi.fn(),
  },
}))
vi.mock('../services/api-roll', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/api-roll')>()
  return { ...actual, readRollSnoozes: vi.fn(() => []) }
})
vi.mock('../services/api-threads', () => ({ threadsApi: { list: vi.fn() } }))

const mockedPending = vi.mocked(useRollPendingSelection)
const mockedResources = vi.mocked(rollResourcesApi)
const mockedSnoozes = vi.mocked(readRollSnoozes)
const mockedThreadsList = vi.mocked(threadsApi.list)

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

function Wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
}

describe('useRollState composed scoped view', () => {
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
    mockedResources.lastRead.mockResolvedValue(null)
    mockedResources.eligibleIssueIds.mockResolvedValue({
      die: 6,
      issue_ids: [10],
      thread_ids: [3],
      pool_reason: 'ready',
    })
    mockedResources.issueCards.mockResolvedValue({ items: [card(10, 3, 'unread')] })
    mockedResources.recovery.mockResolvedValue(null)
    mockedSnoozes.mockReturnValue([])
    mockedThreadsList.mockResolvedValue({ threads: [], active_count: 0, next_page_token: null })
  })

  it('includes the committed rate last-read record in the composed view model', async () => {
    queryClient.setQueryData(queryKeys.roll.lastRead(), {
      roll_reconciliation: { last_read: LAST_READ },
    })

    const { result } = renderHook(() => useRollState(), { wrapper: Wrapper })
    await waitFor(() => expect(result.current.isPending).toBe(false))

    expect(result.current.data?.last_read).toEqual(LAST_READ)
    expect(result.current.data?.roll_pool).toHaveLength(1)
    expect(result.current.data?.roll_recovery).toBeNull()
    expect(result.current.data?.session_id).toBeUndefined()
  })

  it('loads the exact pending card when the eligible pool excludes it', async () => {
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

    mockedResources.eligibleIssueIds.mockResolvedValue({
      die: 6,
      issue_ids: [20],
      thread_ids: [4],
      pool_reason: 'ready',
    })
    mockedResources.issueCards.mockImplementation(async (ids: readonly number[]) => ({
      items: ids.includes(10) ? [card(10, 3, 'unread')] : [card(20, 4, 'unread')],
    }))

    const { result } = renderHook(() => useRollState(), { wrapper: Wrapper })
    await waitFor(() => expect(result.current.isPending).toBe(false))

    expect(mockedResources.issueCards).toHaveBeenCalledWith([10])
    expect(result.current.data?.pending_thread_id).toBe(3)
    expect(result.current.data?.last_rolled_result).toBe(6)
    expect(result.current.data?.active_thread).toMatchObject({
      id: 3,
      title: 'Current Series',
      issue_id: 10,
    })
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
      die: 6,
      issue_ids: [20],
      thread_ids: [4],
      pool_reason: 'ready',
    })
    mockedResources.issueCards.mockImplementation(async (ids: readonly number[]) => {
      if (ids.includes(10)) return { items: [card(10, 3, 'unread')] }
      if (ids.includes(9)) return { items: [card(9, 7, 'unread')] }
      return { items: [card(20, 4, 'unread')] }
    })
    mockedResources.recovery.mockResolvedValue({
      original_thread_id: 3,
      original_thread_title: 'Current Series',
      direct_blockers: [{
        rule_id: null,
        source_type: 'issue',
        source_id: 9,
        source_label: 'Earlier Series #9',
        satisfaction_type: 'item_read',
        satisfied: false,
        causing_issue_ids: [9],
        causing_member_issue_ids: [],
        note: 'reader',
      }],
      readable_prerequisites: [
        { node_type: 'issue', node_id: 9, label: 'Earlier Series #9', is_readable: true },
      ],
      chains: [[
        { node_type: 'issue', node_id: 3, label: 'Current Series #10', is_readable: false },
        { node_type: 'issue', node_id: 9, label: 'Earlier Series #9', is_readable: true },
      ]],
      diagnostics: [],
    })

    const { result } = renderHook(() => useRollState(), { wrapper: Wrapper })
    await waitFor(() => expect(result.current.data?.roll_recovery).not.toBeNull())

    expect(mockedResources.recovery).toHaveBeenCalledWith(10, [])
    expect(result.current.data?.roll_recovery?.direct_blockers[0].source_id).toBe(9)
    expect(result.current.data?.roll_recovery?.readable_prerequisites[0].node_id).toBe(9)
  })

  it('composes snoozed-series chips from one bounded scoped thread page', async () => {
    mockedSnoozes.mockReturnValue([7])
    mockedThreadsList.mockResolvedValue({
      active_count: 1,
      threads: [{
        id: 7,
        title: 'Snoozed Series',
        format: 'Comic',
        status: 'active',
        blocking_reasons: [],
        created_at: '2026-11-28T00:00:00Z',
        is_blocked: false,
        issues_remaining: 3,
        last_activity_at: null,
        queue_position: 1,
      }],
    })

    const { result } = renderHook(() => useRollState(), { wrapper: Wrapper })
    await waitFor(() => expect(result.current.data?.snoozed_threads).toHaveLength(1))

    expect(mockedThreadsList).toHaveBeenCalledWith({ ids: '7', page_size: 1 })
    expect(result.current.data?.snoozed_threads[0]).toMatchObject({
      id: 7,
      title: 'Snoozed Series',
    })
    expect(result.current.data?.snoozed_count).toBe(1)
  })

  it('reflects a snooze-cookie change without remounting', async () => {
    mockedSnoozes.mockReturnValue([])
    const { result, rerender } = renderHook(() => useRollState(), { wrapper: Wrapper })
    await waitFor(() => expect(result.current.isPending).toBe(false))
    expect(result.current.data?.snoozed_threads).toHaveLength(0)

    mockedSnoozes.mockReturnValue([7])
    mockedThreadsList.mockResolvedValue({
      active_count: 1,
      threads: [{
        id: 7,
        title: 'Newly Snoozed',
        format: 'Comic',
        status: 'active',
        blocking_reasons: [],
        created_at: '2026-11-28T00:00:00Z',
        is_blocked: false,
        issues_remaining: 3,
        last_activity_at: null,
        queue_position: 1,
      }],
    })
    rerender()

    await waitFor(() => expect(result.current.data?.snoozed_threads).toHaveLength(1))
    expect(result.current.data?.snoozed_threads[0]?.title).toBe('Newly Snoozed')
    expect(result.current.data?.snoozed_count).toBe(1)
  })

  it('stays empty while the scoped pool has no visible cards', async () => {
    mockedResources.eligibleIssueIds.mockResolvedValue({
      die: 6,
      issue_ids: [],
      thread_ids: [],
      pool_reason: 'no_series',
    })

    const { result } = renderHook(() => useRollState(), { wrapper: Wrapper })
    await waitFor(() => expect(result.current.isPending).toBe(false))

    expect(result.current.data?.roll_pool).toEqual([])
    expect(result.current.data?.pool_reason).toBe('no_series')
    expect(result.current.data?.last_read).toBeNull()
  })
})
