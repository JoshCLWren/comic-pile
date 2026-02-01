import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import {
  useRestoreSessionStart,
  useSession,
  useSessionDetails,
  useSessionSnapshots,
  useSessions,
} from '../hooks/useSession'
import { sessionApi } from '../services/api'

vi.mock('../services/api', () => ({
  sessionApi: {
    getCurrent: vi.fn(),
    list: vi.fn(),
    getDetails: vi.fn(),
    getSnapshots: vi.fn(),
    restoreSessionStart: vi.fn(),
  },
}))

beforeEach(() => {
  sessionApi.getCurrent.mockResolvedValue({ id: 1 })
  sessionApi.list.mockResolvedValue([{ id: 2 }])
  sessionApi.getDetails.mockResolvedValue({ session_id: 3 })
  sessionApi.getSnapshots.mockResolvedValue({ snapshots: [] })
  sessionApi.restoreSessionStart.mockResolvedValue({})
})

it('loads current session', async () => {
  const { result } = renderHook(() => useSession())

  await waitFor(() => expect(result.current.data).toEqual({ id: 1 }))
  expect(sessionApi.getCurrent).toHaveBeenCalled()
})

it('loads session list', async () => {
  const { result } = renderHook(() => useSessions({ status: 'done' }))

  await waitFor(() => expect(result.current.data).toEqual([{ id: 2 }]))
  expect(sessionApi.list).toHaveBeenCalledWith({ status: 'done' })
})

it('loads session details and snapshots', async () => {
  const { result: detailsResult } = renderHook(() => useSessionDetails(3))
  const { result: snapshotsResult } = renderHook(() => useSessionSnapshots(3))

  await waitFor(() => expect(detailsResult.current.data).toEqual({ session_id: 3 }))
  await waitFor(() => expect(snapshotsResult.current.data).toEqual({ snapshots: [] }))
  expect(sessionApi.getDetails).toHaveBeenCalledWith(3)
  expect(sessionApi.getSnapshots).toHaveBeenCalledWith(3)
})

it('restores session start', async () => {
  const { result } = renderHook(() => useRestoreSessionStart())

  await act(async () => {
    await result.current.mutate(11)
  })

  expect(sessionApi.restoreSessionStart).toHaveBeenCalledWith(11)
})
