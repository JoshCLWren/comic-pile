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
import { ToastProvider } from '../contexts/ToastContext'
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

it('loads session list', async () => {
  const { result } = renderWithProvider(() => useSessions({ status: 'done' }))

  await waitFor(() => expect(result.current.data).toEqual([{ id: 2 }]))
  expect(mockedSessionApi.list).toHaveBeenCalledWith({ status: 'done', page_size: 200 })
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
