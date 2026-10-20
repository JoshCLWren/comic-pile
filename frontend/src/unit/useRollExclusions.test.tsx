import { act, renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ROLL_EXCLUSION_PAGE_SIZE, useRollExclusions } from '../hooks/useRollExclusions'
import type { RollExclusionPageResponse, ThreadExclusionReason } from '../types/rollBootstrap'

function items(from: number, to: number): ThreadExclusionReason[] {
  return Array.from({ length: to - from + 1 }, (_, index) => {
    const id = from + index
    return {
      thread_id: id,
      title: `Series ${id}`,
      format: 'Comic',
      reason: 'blocked' as const,
      detail: null,
    }
  })
}

function page(
  offset: number,
  pageItems: ThreadExclusionReason[],
  total: number,
): RollExclusionPageResponse {
  const loadedThrough = offset + pageItems.length
  return {
    category: 'blocked',
    items: pageItems,
    total,
    limit: ROLL_EXCLUSION_PAGE_SIZE,
    offset,
    next_cursor: loadedThrough < total ? String(loadedThrough) : null,
  }
}

const api = { list: vi.fn() }

function renderExclusions(initialProps: { enabled: boolean }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return renderHook(
    ({ enabled }: { enabled: boolean }) =>
      useRollExclusions('blocked', { enabled, api }),
    {
      initialProps,
      wrapper: ({ children }: { children: React.ReactNode }) => (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      ),
    },
  )
}

beforeEach(() => {
  api.list.mockReset()
})

describe('useRollExclusions', () => {
  it('does not fetch until the section is expanded, then pages through the category', async () => {
    api.list
      .mockResolvedValueOnce(page(0, items(1, 20), 25))
      .mockResolvedValueOnce(page(20, items(21, 25), 25))

    const { result, rerender } = renderExclusions({ enabled: false })
    expect(api.list).not.toHaveBeenCalled()

    rerender({ enabled: true })

    await waitFor(() => expect(result.current.items).toHaveLength(20))
    expect(api.list).toHaveBeenNthCalledWith(1, 'blocked', {
      limit: ROLL_EXCLUSION_PAGE_SIZE,
      offset: 0,
    })
    expect(result.current.total).toBe(25)
    expect(result.current.hasNextPage).toBe(true)

    await act(async () => {
      await result.current.fetchNextPage()
    })

    expect(api.list).toHaveBeenNthCalledWith(2, 'blocked', {
      limit: ROLL_EXCLUSION_PAGE_SIZE,
      offset: 20,
    })
    await waitFor(() => expect(result.current.items).toHaveLength(25))
    expect(result.current.items.at(-1)?.thread_id).toBe(25)
    expect(result.current.total).toBe(25)
    expect(result.current.hasNextPage).toBe(false)
    expect(result.current.nextPageToken).toBeNull()
  })

  it('exposes a retryable error without dropping the loaded page', async () => {
    api.list
      .mockResolvedValueOnce(page(0, items(1, 20), 40))
      .mockRejectedValueOnce(new Error('network down'))
      .mockResolvedValueOnce(page(20, items(21, 40), 40))

    const { result } = renderExclusions({ enabled: true })

    await waitFor(() => expect(result.current.items).toHaveLength(20))

    await act(async () => {
      await result.current.fetchNextPage()
    })
    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(result.current.items).toHaveLength(20)

    // The next-page fetch is retryable from the same paginator; loaded rows stay.
    await act(async () => {
      await result.current.fetchNextPage()
    })
    await waitFor(() => expect(result.current.items).toHaveLength(40))
    expect(result.current.isError).toBe(false)
    expect(result.current.total).toBe(40)
  })

  it('retries the missing page instead of reloading the pages already read', async () => {
    api.list
      .mockResolvedValueOnce(page(0, items(1, 20), 40))
      .mockRejectedValueOnce(new Error('network down'))
      .mockResolvedValueOnce(page(20, items(21, 40), 40))

    const { result } = renderExclusions({ enabled: true })

    await waitFor(() => expect(result.current.items).toHaveLength(20))

    await act(async () => {
      await result.current.fetchNextPage()
    })
    await waitFor(() => expect(result.current.isError).toBe(true))

    api.list.mockClear()

    await act(async () => {
      await result.current.retry()
    })

    // The retry asks for the page that failed, not the first page the reader
    // already read (#3330).
    expect(api.list).toHaveBeenCalledTimes(1)
    expect(api.list).toHaveBeenCalledWith('blocked', {
      limit: ROLL_EXCLUSION_PAGE_SIZE,
      offset: 20,
    })
    await waitFor(() => expect(result.current.items).toHaveLength(40))
    expect(result.current.isError).toBe(false)
  })

  it('refetches the first page when the initial load failed', async () => {
    api.list
      .mockRejectedValueOnce(new Error('network down'))
      .mockResolvedValueOnce(page(0, items(1, 20), 20))

    const { result } = renderExclusions({ enabled: true })

    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(result.current.items).toHaveLength(0)

    await act(async () => {
      await result.current.retry()
    })

    // Nothing was loaded yet, so the retry starts the collection over.
    expect(api.list).toHaveBeenNthCalledWith(2, 'blocked', {
      limit: ROLL_EXCLUSION_PAGE_SIZE,
      offset: 0,
    })
    await waitFor(() => expect(result.current.items).toHaveLength(20))
    expect(result.current.isError).toBe(false)
  })

  it('reports the authoritative total when the category is empty', async () => {
    api.list.mockResolvedValueOnce(page(0, [], 0))

    const { result } = renderExclusions({ enabled: true })

    await waitFor(() => expect(api.list).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(result.current.items).toHaveLength(0))
    expect(result.current.total).toBe(0)
    expect(result.current.hasNextPage).toBe(false)
  })
})
