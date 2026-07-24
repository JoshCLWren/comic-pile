import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import {
  useRestoreSessionStart,
  useSession,
  useSessionDetails,
  useSessionSnapshots,
  useSessions,
} from '../hooks/useSession'
import { sessionApi } from '../services/api'
import { ToastProvider } from '../contexts/ToastProvider'
import { CacheProvider } from '../contexts/CacheContext'

vi.mock('../services/api', () => ({
  sessionApi: {
    getCurrent: vi.fn(),
    list: vi.fn(),
    getDetails: vi.fn(),
    getSnapshots: vi.fn(),
    restoreSessionStart: vi.fn(),
  },
}))

const mockedSessionApi = vi.mocked(sessionApi)

function renderWithProvider<T>(hook: () => T): { result: { current: T } } {
  return renderHook(hook, {
    wrapper: ({ children }: { children: ReactNode }) => (
      <CacheProvider>
        <ToastProvider>{children}</ToastProvider>
      </CacheProvider>
    ),
  })
}

beforeEach(() => {
  mockedSessionApi.getCurrent.mockResolvedValue({ id: 1 } as never)
  mockedSessionApi.list.mockResolvedValue({ sessions: [{ id: 2 }], next_page_token: null } as never)
  mockedSessionApi.getDetails.mockResolvedValue({ session_id: 3 } as never)
  mockedSessionApi.getSnapshots.mockResolvedValue({ snapshots: [] } as never)
  mockedSessionApi.restoreSessionStart.mockResolvedValue({} as never)
})

it('loads current session', async () => {
  const { result } = renderWithProvider(() => useSession())

  await waitFor(() => expect(result.current.data).toEqual({ id: 1 }))
  expect(mockedSessionApi.getCurrent).toHaveBeenCalled()
})

it('loads first page of sessions', async () => {
  const { result } = renderWithProvider(() => useSessions({ status: 'done' }))

  await waitFor(() => expect(result.current.data).toEqual([{ id: 2 }]))
  expect(mockedSessionApi.list).toHaveBeenCalledWith({ status: 'done' }, null)
  expect(result.current.hasMore).toBe(false)
})

it('paginates with loadMore and deduplicates sessions', async () => {
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

it('restores session start', async () => {
  const { result } = renderWithProvider(() => useRestoreSessionStart())

  await act(async () => {
    await result.current.mutate(11)
  })

  expect(mockedSessionApi.restoreSessionStart).toHaveBeenCalledWith(11)
})

it('handles empty ids, non-Error failures, persisted session changes, and restore errors', async () => {
  const emptyDetails = renderWithProvider(() => useSessionDetails(null))
  const emptySnapshots = renderWithProvider(() => useSessionSnapshots(undefined))
  expect(emptyDetails.result.current.isPending).toBe(false)
  expect(emptySnapshots.result.current.isPending).toBe(false)

  const storage = new Map<string, string>()
  Object.defineProperty(window, 'localStorage', { configurable: true, value: {
    getItem: (key: string) => storage.get(key) ?? null,
    setItem: (key: string, value: string) => storage.set(key, value),
    removeItem: (key: string) => storage.delete(key),
  } })
  mockedSessionApi.getCurrent.mockResolvedValueOnce({ id: 8, user_id: 4 } as never)
  window.localStorage.setItem('comic_pile_last_session_id_4', '7')
  const current = renderWithProvider(() => useSession())
  await waitFor(() => expect(current.result.current.data).toEqual({ id: 8, user_id: 4 }))

  mockedSessionApi.getDetails.mockRejectedValueOnce('details failed')
  const details = renderWithProvider(() => useSessionDetails(8))
  await waitFor(() => expect(details.result.current.error?.message).toBe('Failed to fetch session details'))
  mockedSessionApi.getSnapshots.mockRejectedValueOnce('snapshots failed')
  const snapshots = renderWithProvider(() => useSessionSnapshots(8))
  await waitFor(() => expect(snapshots.result.current.error?.message).toBe('Failed to fetch session snapshots'))

  mockedSessionApi.restoreSessionStart.mockRejectedValueOnce('restore failed')
  const restore = renderWithProvider(() => useRestoreSessionStart())
  await act(async () => {
    await expect(restore.result.current.mutate(8)).rejects.toBe('restore failed')
  })
  expect(restore.result.current.isError).toBe(true)
  expect(restore.result.current.error?.message).toBe('Failed to restore session')
})

it('continues when session storage cannot be read or written', async () => {
  Object.defineProperty(window, 'localStorage', { configurable: true, value: {
    getItem: () => { throw new Error('storage read blocked') },
    setItem: () => { throw new Error('storage write blocked') },
    removeItem: () => { throw new Error('storage remove blocked') },
  } })
  mockedSessionApi.getCurrent.mockResolvedValueOnce({ id: 12, user_id: 6 } as never)
  const { result } = renderWithProvider(() => useSession())
  await waitFor(() => expect(result.current.data).toEqual({ id: 12, user_id: 6 }))
  expect(result.current.isError).toBe(false)
})

it('normalizes Error failures for session list and restore operations', async () => {
  mockedSessionApi.list.mockRejectedValueOnce(new Error('list unavailable'))
  const list = renderWithProvider(() => useSessions())
  await waitFor(() => expect(list.result.current.error?.message).toBe('list unavailable'))

  mockedSessionApi.restoreSessionStart.mockRejectedValueOnce(new Error('restore unavailable'))
  const restore = renderWithProvider(() => useRestoreSessionStart())
  await expect(act(async () => restore.result.current.mutate(8))).rejects.toThrow('restore unavailable')
})

it('preserves Error instances from detail and snapshot requests', async () => {
  mockedSessionApi.getDetails.mockRejectedValueOnce(new Error('detail unavailable'))
  mockedSessionApi.getSnapshots.mockRejectedValueOnce(new Error('snapshot unavailable'))
  const details = renderWithProvider(() => useSessionDetails(12))
  const snapshots = renderWithProvider(() => useSessionSnapshots(12))
  await waitFor(() => expect(details.result.current.error?.message).toBe('detail unavailable'))
  await waitFor(() => expect(snapshots.result.current.error?.message).toBe('snapshot unavailable'))
})

it('reports current-session failures and tolerates a malformed current response', async () => {
  mockedSessionApi.getCurrent.mockRejectedValueOnce(new Error('current unavailable'))
  const failed = renderWithProvider(() => useSession())
  await waitFor(() => expect(failed.result.current.error?.message).toBe('current unavailable'))

  mockedSessionApi.getCurrent.mockResolvedValueOnce({ id: null } as never)
  const malformed = renderWithProvider(() => useSession())
  await waitFor(() => expect(malformed.result.current.isPending).toBe(false))

  mockedSessionApi.getCurrent.mockRejectedValueOnce('current string failure')
  const stringFailure = renderWithProvider(() => useSession())
  await waitFor(() => expect(stringFailure.result.current.error?.message).toBe('Failed to fetch current session'))
})
