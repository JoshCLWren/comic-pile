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
import { createQueryWrapper, createTestQueryClient } from './testUtils'

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
  const queryClient = createTestQueryClient()
  const wrapper = createQueryWrapper(queryClient)
  const { result } = renderHook(() => useSession(), { wrapper })

  await waitFor(() => expect(result.current.data).toEqual({ id: 1 }))
  expect(sessionApi.getCurrent).toHaveBeenCalled()
})

it('loads session list', async () => {
  const queryClient = createTestQueryClient()
  const wrapper = createQueryWrapper(queryClient)
  const { result } = renderHook(() => useSessions({ status: 'done' }), { wrapper })

  await waitFor(() => expect(result.current.data).toEqual([{ id: 2 }]))
  expect(sessionApi.list).toHaveBeenCalledWith({ status: 'done' })
})

it('loads session details and snapshots', async () => {
  const queryClient = createTestQueryClient()
  const wrapper = createQueryWrapper(queryClient)
  const { result: detailsResult } = renderHook(() => useSessionDetails(3), { wrapper })
  const { result: snapshotsResult } = renderHook(() => useSessionSnapshots(3), { wrapper })

  await waitFor(() => expect(detailsResult.current.data).toEqual({ session_id: 3 }))
  await waitFor(() => expect(snapshotsResult.current.data).toEqual({ snapshots: [] }))
  expect(sessionApi.getDetails).toHaveBeenCalledWith(3)
  expect(sessionApi.getSnapshots).toHaveBeenCalledWith(3)
})

it('restores session start and invalidates queries', async () => {
  const queryClient = createTestQueryClient()
  const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')
  const wrapper = createQueryWrapper(queryClient)
  const { result } = renderHook(() => useRestoreSessionStart(), { wrapper })

  await act(async () => {
    await result.current.mutateAsync(11)
  })

  expect(sessionApi.restoreSessionStart).toHaveBeenCalledWith(11)
  await waitFor(() => expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['session'] }))
  await waitFor(() => expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['sessions'] }))
  await waitFor(() => expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['threads'] }))
})
