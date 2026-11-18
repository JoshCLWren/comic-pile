import { act, renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import {
  useSessionDetails,
  useSessionSnapshots,
  useSessions,
} from '../hooks/useSession'
import { sessionApi } from '../services/api-sessions'
import { ToastProvider } from '../contexts/ToastProvider'
import { queryKeys } from '../query/queryKeys'

vi.mock('../services/api-sessions', () => ({
  sessionApi: {
    list: vi.fn(),
    getDetails: vi.fn(),
    getSnapshots: vi.fn(),
  },
}))

const mockedSessionApi = vi.mocked(sessionApi)

function renderWithProvider<T>(hook: () => T): { result: { current: T } } {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return renderHook(hook, {
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>
        <ToastProvider>{children}</ToastProvider>
      </QueryClientProvider>
    ),
  })
}

function renderWithClient<T>(hook: () => T) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  const rendered = renderHook(hook, {
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>
        <ToastProvider>{children}</ToastProvider>
      </QueryClientProvider>
    ),
  })
  return { result: rendered.result, client }
}

beforeEach(() => {
  // SAFETY: mock payload supplies only the fields this test asserts
  mockedSessionApi.list.mockResolvedValue({ sessions: [{ id: 2 }], next_page_token: null } as never)
  // SAFETY: mock payload supplies only the fields this test asserts
  mockedSessionApi.getDetails.mockResolvedValue({ session_id: 3 } as never)
  // SAFETY: mock payload supplies only the fields this test asserts
  mockedSessionApi.getSnapshots.mockResolvedValue({ snapshots: [] } as never)
})

it('loads first page of sessions', async () => {
  const { result } = renderWithProvider(() => useSessions({ status: 'done' }))

  await waitFor(() => expect(result.current.data).toEqual([{ id: 2 }]))
  expect(mockedSessionApi.list).toHaveBeenCalledWith({ status: 'done' }, null)
  expect(result.current.hasMore).toBe(false)
})

it('is invalidated by queryKeys.session.pages() and queryKeys.session.all', async () => {
  // SAFETY: the stubbed page supplies only the fields the session pager reads
  mockedSessionApi.list
    .mockReset()
    .mockResolvedValueOnce({ sessions: [{ id: 1 }], next_page_token: null } as never)
    .mockResolvedValueOnce({ sessions: [{ id: 2 }], next_page_token: null } as never)

  const { result, client } = renderWithClient(() => useSessions())

  await waitFor(() => expect(result.current.data).toEqual([{ id: 1 }]))
  expect(mockedSessionApi.list).toHaveBeenCalledTimes(1)

  await act(async () => {
    await client.invalidateQueries({ queryKey: queryKeys.session.pages() })
  })

  await waitFor(() => expect(mockedSessionApi.list).toHaveBeenCalledTimes(2))
  await waitFor(() => expect(result.current.data).toEqual([{ id: 2 }]))

  await act(async () => {
    await client.invalidateQueries({ queryKey: queryKeys.session.all })
  })

  await waitFor(() => expect(mockedSessionApi.list).toHaveBeenCalledTimes(3))
  await waitFor(() => expect(result.current.data).toEqual([{ id: 2 }]))
})

it('paginates with loadMore and deduplicates sessions', async () => {
  // SAFETY: the stubbed page supplies only the fields the session pager reads
  mockedSessionApi.list
    .mockReset()
    .mockResolvedValueOnce({ sessions: [{ id: 1 }], next_page_token: 'token2' } as never)
    .mockResolvedValueOnce({ sessions: [{ id: 2 }], next_page_token: 'token3' } as never)

  const { result } = renderWithProvider(() => useSessions())

  await waitFor(() => {
    expect(result.current.data).toEqual([{ id: 1 }])
    expect(result.current.hasMore).toBe(true)
  })

  await act(async () => {
    result.current.loadMore()
  })

  await waitFor(() => {
    expect(result.current.data).toEqual([{ id: 1 }, { id: 2 }])
  })
  expect(mockedSessionApi.list).toHaveBeenCalledTimes(2)
  expect(mockedSessionApi.list).toHaveBeenNthCalledWith(1, {}, null)
  expect(mockedSessionApi.list).toHaveBeenNthCalledWith(2, {}, 'token2')
})

it('deduplicates sessions when loading more pages', async () => {
  // SAFETY: the stubbed page supplies only the fields the session pager reads
  mockedSessionApi.list
    .mockReset()
    .mockResolvedValueOnce({ sessions: [{ id: 1 }, { id: 2 }], next_page_token: 'token2' } as never)
    .mockResolvedValueOnce({ sessions: [{ id: 2 }, { id: 3 }], next_page_token: null } as never)

  const { result } = renderWithProvider(() => useSessions())

  await waitFor(() => {
    expect(result.current.data).toEqual([{ id: 1 }, { id: 2 }])
  })

  await act(async () => {
    result.current.loadMore()
  })

  await waitFor(() => {
    // id: 2 appears in both pages but should not be duplicated
    expect(result.current.data).toEqual([{ id: 1 }, { id: 2 }, { id: 3 }])
  })
})

it('handles list errors gracefully', async () => {
  mockedSessionApi.list
    .mockReset()
    .mockRejectedValueOnce(new Error('Network error'))

  const { result } = renderWithProvider(() => useSessions())

  await waitFor(() => expect(result.current.isError).toBe(true))
  await waitFor(() => expect(result.current.isPending).toBe(false))
  expect(result.current.error).toBeInstanceOf(Error)
})

it('loads session details and snapshots', async () => {
  const { result: detailsResult } = renderWithProvider(() => useSessionDetails(3))
  const { result: snapshotsResult } = renderWithProvider(() => useSessionSnapshots(3))

  await waitFor(() => expect(detailsResult.current.data).toEqual({ session_id: 3 }))
  await waitFor(() => expect(snapshotsResult.current.data).toEqual({ snapshots: [] }))
  expect(mockedSessionApi.getDetails).toHaveBeenCalledWith(3)
  expect(mockedSessionApi.getSnapshots).toHaveBeenCalledWith(3)
})

it('handles empty ids and non-Error failures', async () => {
  const emptyDetails = renderWithProvider(() => useSessionDetails(null))
  const emptySnapshots = renderWithProvider(() => useSessionSnapshots(undefined))
  expect(emptyDetails.result.current.isPending).toBe(false)
  expect(emptySnapshots.result.current.isPending).toBe(false)

  mockedSessionApi.getDetails.mockRejectedValueOnce('details failed')
  const details = renderWithProvider(() => useSessionDetails(8))
  await waitFor(() => expect(details.result.current.error?.message).toBe('Failed to fetch session details'))
  mockedSessionApi.getSnapshots.mockRejectedValueOnce('snapshots failed')
  const snapshots = renderWithProvider(() => useSessionSnapshots(8))
  await waitFor(() => expect(snapshots.result.current.error?.message).toBe('Failed to fetch session snapshots'))
})

it('normalizes Error failures for the session list', async () => {
  mockedSessionApi.list.mockRejectedValueOnce(new Error('list unavailable'))
  const list = renderWithProvider(() => useSessions())
  await waitFor(() => expect(list.result.current.error?.message).toBe('list unavailable'))
})

it('preserves Error instances from detail and snapshot requests', async () => {
  mockedSessionApi.getDetails.mockRejectedValueOnce(new Error('detail unavailable'))
  mockedSessionApi.getSnapshots.mockRejectedValueOnce(new Error('snapshot unavailable'))
  const details = renderWithProvider(() => useSessionDetails(12))
  const snapshots = renderWithProvider(() => useSessionSnapshots(12))
  await waitFor(() => expect(details.result.current.error?.message).toBe('detail unavailable'))
  await waitFor(() => expect(snapshots.result.current.error?.message).toBe('snapshot unavailable'))
})

it('exposes retry progress while the session list is retried after a timeout', async () => {
  mockedSessionApi.list.mockReset().mockRejectedValue(new Error('timeout of 10000ms exceeded'))
  const client = new QueryClient({
    defaultOptions: { queries: { retry: 1, retryDelay: 10 }, mutations: { retry: false } },
  })
  const { result } = renderHook(() => useSessions(), {
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>
        <ToastProvider>{children}</ToastProvider>
      </QueryClientProvider>
    ),
  })

  await waitFor(() => expect(result.current.isError).toBe(true))

  expect(mockedSessionApi.list).toHaveBeenCalledTimes(2)
  expect(result.current.failureCount).toBe(2)
  expect(result.current.isRetrying).toBe(false)
})

it('reports zero session-list failures on the fast path', async () => {
  const { result } = renderWithProvider(() => useSessions())

  await waitFor(() => expect(result.current.isPending).toBe(false))

  expect(result.current.failureCount).toBe(0)
  expect(result.current.isRetrying).toBe(false)
})

it('keeps the bounded retry state while a user-initiated retry is in flight', async () => {
  // refetch() resets React Query's failureCount to 0, so the bounded loading
  // state has to be latched or HistoryPage drops the user back onto the bare
  // loading splash the moment they press Retry (issue #3429).
  let release!: () => void
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  mockedSessionApi.list.mockReset()
  mockedSessionApi.list
    .mockRejectedValueOnce(new Error('timeout of 10000ms exceeded'))
    .mockRejectedValueOnce(new Error('timeout of 10000ms exceeded'))
    .mockImplementationOnce(() =>
      // SAFETY: the stubbed page supplies only the fields the session pager reads
      gate.then(() => ({ sessions: [{ id: 2 }], next_page_token: null } as never)),
    )
  const client = new QueryClient({
    defaultOptions: { queries: { retry: 1, retryDelay: 10 }, mutations: { retry: false } },
  })
  const { result } = renderHook(() => useSessions(), {
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>
        <ToastProvider>{children}</ToastProvider>
      </QueryClientProvider>
    ),
  })

  await waitFor(() => expect(result.current.isError).toBe(true))

  await act(async () => {
    void result.current.refetch()
  })

  await waitFor(() => expect(result.current.isPending).toBe(true))
  expect(result.current.isRetrying).toBe(true)

  await act(async () => {
    release()
  })

  await waitFor(() => expect(result.current.data).toHaveLength(1))
  expect(result.current.isError).toBe(false)
  expect(result.current.isRetrying).toBe(false)
})
