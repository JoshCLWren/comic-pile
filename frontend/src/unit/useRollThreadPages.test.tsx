import { act, renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  ROLL_SECTION_PAGE_SIZE,
  rollSectionRevision,
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

function createClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
}

function wrapperFor(client: QueryClient) {
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
}

function renderWithClient<T>(hook: () => T) {
  const client = createClient()
  const rendered = renderHook(hook, { wrapper: wrapperFor(client) })
  return { result: rendered.result, client }
}

const api = makeApi()
const mockedBlockedPage = vi.mocked(api.getBlockedThreadsPage)
const mockedInactivePage = vi.mocked(api.getInactiveThreadsPage)

beforeEach(() => {
  vi.clearAllMocks()
})

describe('rollSectionRevision', () => {
  it('stays stable while the category is unchanged', () => {
    expect(rollSectionRevision(25, [1, 2, 3])).toBe(rollSectionRevision(25, [1, 2, 3]))
  })

  it('changes when the counted total changes', () => {
    expect(rollSectionRevision(25, [1, 2, 3])).not.toBe(rollSectionRevision(24, [1, 2, 3]))
  })

  it('changes when the previewed membership changes', () => {
    expect(rollSectionRevision(25, [1, 2, 3])).not.toBe(rollSectionRevision(25, [1, 2, 4]))
  })
})

describe('useRollBlockedThreads', () => {
  it('does not fetch while the section is disabled', () => {
    const { result } = renderWithClient(() =>
      useRollBlockedThreads({ startOffset: 20, revision: '0:', enabled: false, api }),
    )

    expect(mockedBlockedPage).not.toHaveBeenCalled()
    expect(result.current.items).toEqual([])
  })

  it('pages from the preview boundary and stops when the server has no more', async () => {
    mockedBlockedPage.mockResolvedValue(
      blockedPage([thread(21), thread(22), thread(23), thread(24), thread(25)], 20, null),
    )

    const { result } = renderWithClient(() =>
      useRollBlockedThreads({ startOffset: 20, revision: '25:1,2,3', enabled: true, api }),
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
      useRollBlockedThreads({ startOffset: 20, revision: '30:1,2,3', enabled: true, api }),
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

  it('retries the first page when it failed, because no page has loaded', async () => {
    mockedBlockedPage
      .mockRejectedValueOnce(new Error('page request failed'))
      .mockResolvedValueOnce(blockedPage([thread(21)], 20, null))

    const { result } = renderWithClient(() =>
      useRollBlockedThreads({ startOffset: 20, revision: '25:1,2,3', enabled: true, api }),
    )

    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(result.current.items).toEqual([])
    expect(mockedBlockedPage).toHaveBeenCalledTimes(1)

    await act(async () => {
      await result.current.loadMore()
    })

    await waitFor(() => expect(result.current.items).toHaveLength(1))
    expect(mockedBlockedPage).toHaveBeenCalledTimes(2)
    expect(mockedBlockedPage).toHaveBeenNthCalledWith(2, 20, ROLL_SECTION_PAGE_SIZE)
    expect(result.current.isError).toBe(false)
  })

  it('retries a failed later page without re-reading the loaded pages', async () => {
    mockedBlockedPage
      .mockResolvedValueOnce(blockedPage([thread(21)], 20, 21, 30))
      .mockRejectedValueOnce(new Error('page request failed'))
      .mockResolvedValueOnce(blockedPage([thread(22)], 21, null, 30))

    const { result } = renderWithClient(() =>
      useRollBlockedThreads({ startOffset: 20, revision: '30:1,2,3', enabled: true, api }),
    )

    await waitFor(() => expect(result.current.items).toHaveLength(1))

    await act(async () => {
      await result.current.loadMore()
    })

    await waitFor(() => expect(result.current.isError).toBe(true))

    await act(async () => {
      await result.current.loadMore()
    })

    await waitFor(() => expect(result.current.items).toHaveLength(2))
    expect(mockedBlockedPage).toHaveBeenCalledTimes(3)
    expect(mockedBlockedPage).toHaveBeenNthCalledWith(3, 21, ROLL_SECTION_PAGE_SIZE)
    expect(result.current.isError).toBe(false)
  })

  it('reads fresh pages when the category revision changes', async () => {
    mockedBlockedPage
      .mockResolvedValueOnce(blockedPage([thread(21)], 20, null))
      .mockResolvedValueOnce(blockedPage([thread(31)], 20, null))

    const client = createClient()
    const { result, rerender } = renderHook(
      ({ revision }: { revision: string }) =>
        useRollBlockedThreads({ startOffset: 20, revision, enabled: true, api }),
      {
        initialProps: { revision: '25:1,2,3' },
        wrapper: wrapperFor(client),
      },
    )

    await waitFor(() => expect(result.current.items.map((item) => item.id)).toEqual([21]))
    expect(mockedBlockedPage).toHaveBeenCalledTimes(1)

    rerender({ revision: '24:1,2,4' })

    await waitFor(() => expect(result.current.items.map((item) => item.id)).toEqual([31]))
    expect(mockedBlockedPage).toHaveBeenCalledTimes(2)
  })

  it('builds the canonical blocked-page key with the preview boundary and revision', () => {
    expect(
      queryKeys.roll.blockedThreads({
        pageSize: ROLL_SECTION_PAGE_SIZE,
        startOffset: 20,
        revision: '25:1,2,3',
      }),
    ).toEqual([
      'roll',
      'blocked-threads',
      { pageSize: ROLL_SECTION_PAGE_SIZE, startOffset: 20, revision: '25:1,2,3' },
    ])
  })
})

describe('useRollInactiveThreads', () => {
  it('pages the out-of-pool category from the preview boundary', async () => {
    mockedInactivePage.mockResolvedValue(
      inactivePage([inactive(21), inactive(22)], 20, null),
    )

    const { result } = renderWithClient(() =>
      useRollInactiveThreads({ startOffset: 20, revision: '25:1,2,3', enabled: true, api }),
    )

    await waitFor(() => expect(result.current.items).toHaveLength(2))
    expect(mockedInactivePage).toHaveBeenCalledWith(20, ROLL_SECTION_PAGE_SIZE)
    expect(result.current.items.map((item) => item.thread_id)).toEqual([21, 22])
  })

  it('retries the first page when it failed, because no page has loaded', async () => {
    mockedInactivePage
      .mockRejectedValueOnce(new Error('page request failed'))
      .mockResolvedValueOnce(inactivePage([inactive(21)], 20, null))

    const { result } = renderWithClient(() =>
      useRollInactiveThreads({ startOffset: 20, revision: '25:1,2,3', enabled: true, api }),
    )

    await waitFor(() => expect(result.current.isError).toBe(true))

    await act(async () => {
      await result.current.loadMore()
    })

    await waitFor(() => expect(result.current.items).toHaveLength(1))
    expect(mockedInactivePage).toHaveBeenCalledTimes(2)
    expect(result.current.isError).toBe(false)
  })
})
