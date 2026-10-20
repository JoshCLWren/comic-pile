import { act, renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  ROLL_SECTION_PAGE_SIZE,
  useRollBlockedThreads,
  useRollInactiveThreads,
} from '../hooks/useRollThreadPages'
import type { RollThreadPageApi } from '../services/apiTypes'
import { queryKeys } from '../query/queryKeys'
import type {
  RollBlockedThreadsPage,
  RollBootstrapThread,
  RollInactiveThreadsPage,
  ThreadExclusionReason,
} from '../types/rollBootstrap'

function makeApi(): RollThreadPageApi {
  return {
    getBlockedThreadsPage: vi.fn(),
    getInactiveThreadsPage: vi.fn(),
  }
}

function thread(id: number): RollBootstrapThread {
  return { id, title: `Series ${id}`, format: 'Comic' }
}

function inactive(threadId: number): ThreadExclusionReason {
  return {
    thread_id: threadId,
    title: `Series ${threadId}`,
    format: 'Comic',
    reason: 'completed',
    detail: 'Read the full series',
  }
}

function blockedPage(
  items: RollBootstrapThread[],
  offset: number,
  nextOffset: number | null,
  total = 25,
): RollBlockedThreadsPage {
  return { total, offset, limit: ROLL_SECTION_PAGE_SIZE, next_offset: nextOffset, items }
}

function inactivePage(
  items: ThreadExclusionReason[],
  offset: number,
  nextOffset: number | null,
  total = 25,
): RollInactiveThreadsPage {
  return { total, offset, limit: ROLL_SECTION_PAGE_SIZE, next_offset: nextOffset, items }
}

function renderWithClient<T>(hook: () => T) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const rendered = renderHook(hook, {
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  })
  return { result: rendered.result, client }
}

const api = makeApi()
const mockedBlockedPage = vi.mocked(api.getBlockedThreadsPage)
const mockedInactivePage = vi.mocked(api.getInactiveThreadsPage)

beforeEach(() => {
  vi.clearAllMocks()
})

describe('useRollBlockedThreads', () => {
  it('does not fetch while the section is disabled', () => {
    const { result } = renderWithClient(() =>
      useRollBlockedThreads({ startOffset: 20, enabled: false, api }),
    )

    expect(mockedBlockedPage).not.toHaveBeenCalled()
    expect(result.current.items).toEqual([])
  })

  it('pages from the preview boundary and stops when the server has no more', async () => {
    mockedBlockedPage.mockResolvedValue(
      blockedPage([thread(21), thread(22), thread(23), thread(24), thread(25)], 20, null),
    )

    const { result } = renderWithClient(() =>
      useRollBlockedThreads({ startOffset: 20, enabled: true, api }),
    )

    await waitFor(() => expect(result.current.items).toHaveLength(5))
    expect(mockedBlockedPage).toHaveBeenCalledWith(20, ROLL_SECTION_PAGE_SIZE)
    expect(result.current.items.map((item) => item.id)).toEqual([21, 22, 23, 24, 25])
    expect(result.current.isFetching).toBe(false)
  })

  it('loads the next page through loadMore using the server next_offset', async () => {
    mockedBlockedPage
      .mockResolvedValueOnce(blockedPage([thread(21)], 20, 21, 30))
      .mockResolvedValueOnce(blockedPage([thread(22)], 21, null, 30))

    const { result } = renderWithClient(() =>
      useRollBlockedThreads({ startOffset: 20, enabled: true, api }),
    )

    await waitFor(() => expect(result.current.items).toHaveLength(1))

    await act(async () => {
      await result.current.loadMore()
    })

    await waitFor(() => expect(result.current.items).toHaveLength(2))
    expect(mockedBlockedPage).toHaveBeenNthCalledWith(1, 20, ROLL_SECTION_PAGE_SIZE)
    expect(mockedBlockedPage).toHaveBeenNthCalledWith(2, 21, ROLL_SECTION_PAGE_SIZE)
    expect(result.current.items.map((item) => item.id)).toEqual([21, 22])
  })

  it('builds the canonical blocked-page key with the preview boundary', () => {
    expect(
      queryKeys.roll.blockedThreads({
        pageSize: ROLL_SECTION_PAGE_SIZE,
        startOffset: 20,
      }),
    ).toEqual(['roll', 'blocked-threads', { pageSize: ROLL_SECTION_PAGE_SIZE, startOffset: 20 }])
  })
})

describe('useRollInactiveThreads', () => {
  it('pages the out-of-pool category from the preview boundary', async () => {
    mockedInactivePage.mockResolvedValue(
      inactivePage([inactive(21), inactive(22)], 20, null),
    )

    const { result } = renderWithClient(() =>
      useRollInactiveThreads({ startOffset: 20, enabled: true, api }),
    )

    await waitFor(() => expect(result.current.items).toHaveLength(2))
    expect(mockedInactivePage).toHaveBeenCalledWith(20, ROLL_SECTION_PAGE_SIZE)
    expect(result.current.items.map((item) => item.thread_id)).toEqual([21, 22])
  })
})
