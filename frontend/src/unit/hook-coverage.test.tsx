import { renderHook, waitFor, act } from '@testing-library/react'
import axios from 'axios'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({
  queueApi: { moveToPosition: vi.fn(), moveToFront: vi.fn(), moveToBack: vi.fn(), shuffle: vi.fn() },
  rateApi: { rate: vi.fn() },
  rollApi: { roll: vi.fn(), override: vi.fn(), dismissPending: vi.fn(), setDie: vi.fn(), clearManualDie: vi.fn(), reroll: vi.fn() },
  undoApi: { listSnapshots: vi.fn(), undo: vi.fn() },
  tasksApi: { getMetrics: vi.fn() },
  sessionApi: { getCurrent: vi.fn(), list: vi.fn(), getDetails: vi.fn(), getSnapshots: vi.fn(), restoreSessionStart: vi.fn() },
}))
vi.mock('../services/api', () => api)
const toast = vi.hoisted(() => ({ showToast: vi.fn() }))
const cache = vi.hoisted(() => ({ invalidateQueries: vi.fn() }))
vi.mock('../contexts/useToast', () => ({ useToast: () => toast }))
vi.mock('../contexts/useCache', () => ({ useCache: () => cache }))

import { useMoveToBack, useMoveToFront, useMoveToPosition, useShuffleQueue } from '../hooks/useQueue'
import { useRate } from '../hooks/useRate'
import { useClearManualDie, useDismissPending, useOverrideRoll, useReroll, useRoll, useSetDie } from '../hooks/useRoll'
import { useSession, useSessions, useSessionDetails, useSessionSnapshots, useRestoreSessionStart } from '../hooks/useSession'
import { useSnapshots, useUndo } from '../hooks/useUndo'
import { useAnalytics } from '../hooks/useAnalytics'

beforeEach(() => {
  vi.clearAllMocks()
  Object.values(api).forEach((group) => Object.values(group).forEach((fn) => fn.mockResolvedValue({})))
  api.rollApi.roll.mockResolvedValue({ result: 4 })
})

describe('mutation hook success and failure paths', () => {
  it('runs queue and rating mutations', async () => {
    const position = renderHook(() => useMoveToPosition()); await act(async () => await position.result.current.mutate({ id: 1, position: 2 }))
    const front = renderHook(() => useMoveToFront()); await act(async () => await front.result.current.mutate(1))
    const back = renderHook(() => useMoveToBack()); await act(async () => await back.result.current.mutate(1))
    const shuffle = renderHook(() => useShuffleQueue()); await act(async () => await shuffle.result.current.mutate())
    expect(front.result.current.isError).toBe(false)
    const rate = renderHook(() => useRate())
    await act(async () => await rate.result.current.mutate({ thread_id: 1, rating: 4 }))
    expect(api.rateApi.rate).toHaveBeenCalled()
  })

  it('sets error state and rethrows mutation failures', async () => {
    api.queueApi.moveToFront.mockRejectedValueOnce(new Error('bad'))
    const { result } = renderHook(() => useMoveToFront())
    await act(async () => {
      await expect(result.current.mutate(1)).rejects.toThrow('bad')
    })
    expect(result.current.isPending).toBe(false)
    await waitFor(() => expect(result.current.isError).toBe(true))

    api.queueApi.moveToBack.mockRejectedValueOnce(new Error('back failed'))
    const back = renderHook(() => useMoveToBack())
    await act(async () => expect(back.result.current.mutate(1)).rejects.toThrow('back failed'))
    api.queueApi.moveToPosition.mockRejectedValueOnce(new Error('position failed'))
    const position = renderHook(() => useMoveToPosition())
    await act(async () => expect(position.result.current.mutate({ id: 1, position: 2 })).rejects.toThrow('position failed'))
    api.queueApi.shuffle.mockRejectedValueOnce(new Error('shuffle failed'))
    const shuffle = renderHook(() => useShuffleQueue())
    await act(async () => expect(shuffle.result.current.mutate()).rejects.toThrow('shuffle failed'))
    api.rateApi.rate.mockRejectedValueOnce(new Error('rate failed'))
    const rate = renderHook(() => useRate())
    await act(async () => expect(rate.result.current.mutate({ thread_id: 1, rating: 1 })).rejects.toThrow('rate failed'))
  })

  it('runs all roll mutations', async () => {
    const roll = renderHook(() => useRoll()); await act(async () => await roll.result.current.mutate())
    const override = renderHook(() => useOverrideRoll()); await act(async () => await override.result.current.mutate({ thread_id: 1 }))
    const dismiss = renderHook(() => useDismissPending()); await act(async () => await dismiss.result.current.mutate())
    const setDie = renderHook(() => useSetDie()); await act(async () => await setDie.result.current.mutate(6))
    const clearDie = renderHook(() => useClearManualDie()); await act(async () => await clearDie.result.current.mutate())
    const reroll = renderHook(() => useReroll()); await act(async () => await reroll.result.current.mutate())
    expect(roll.result.current.isError).toBe(false)
    api.rollApi.reroll.mockRejectedValueOnce(new Error('fail'))
    const failed = renderHook(() => useReroll())
    await act(async () => {
      await expect(failed.result.current.mutate()).rejects.toThrow('fail')
    })
    expect(failed.result.current.isPending).toBe(false)
    await waitFor(() => expect(failed.result.current.isError).toBe(true))

    api.rollApi.roll.mockRejectedValueOnce(new Error('roll failed'))
    const failedRoll = renderHook(() => useRoll())
    await act(async () => expect(failedRoll.result.current.mutate()).rejects.toThrow('roll failed'))
    api.rollApi.override.mockRejectedValueOnce(new Error('override failed'))
    const failedOverride = renderHook(() => useOverrideRoll())
    await act(async () => expect(failedOverride.result.current.mutate({ thread_id: 1 })).rejects.toThrow('override failed'))
    api.rollApi.dismissPending.mockRejectedValueOnce(new Error('dismiss failed'))
    const failedDismiss = renderHook(() => useDismissPending())
    await act(async () => expect(failedDismiss.result.current.mutate()).rejects.toThrow('dismiss failed'))
    api.rollApi.setDie.mockRejectedValueOnce(new Error('die failed'))
    const failedDie = renderHook(() => useSetDie())
    await act(async () => expect(failedDie.result.current.mutate(6)).rejects.toThrow('die failed'))
    api.rollApi.clearManualDie.mockRejectedValueOnce(new Error('clear failed'))
    const failedClear = renderHook(() => useClearManualDie())
    await act(async () => expect(failedClear.result.current.mutate()).rejects.toThrow('clear failed'))
  })
})

describe('data hooks', () => {
  it('loads analytics and snapshots', async () => {
    api.tasksApi.getMetrics.mockResolvedValue({ total_threads: 1 })
    const analytics = renderHook(() => useAnalytics())
    await waitFor(() => expect(analytics.result.current.data).toEqual({ total_threads: 1 }))
    api.undoApi.listSnapshots.mockResolvedValue({ snapshots: [] })
    const snapshots = renderHook(() => useSnapshots(1))
    await waitFor(() => expect(snapshots.result.current.data).toEqual({ snapshots: [] }))
    const empty = renderHook(() => useSnapshots(null))
    expect(empty.result.current.data).toBeNull()

    api.tasksApi.getMetrics.mockRejectedValueOnce(new Error('metrics failed'))
    const failedAnalytics = renderHook(() => useAnalytics())
    await waitFor(() => expect(failedAnalytics.result.current.error).toBeInstanceOf(Error))
    api.tasksApi.getMetrics.mockRejectedValueOnce('metrics unavailable')
    const stringAnalytics = renderHook(() => useAnalytics())
    await waitFor(() => expect(stringAnalytics.result.current.error?.message).toBe('metrics unavailable'))
    api.undoApi.listSnapshots.mockRejectedValueOnce(new Error('snapshots failed'))
    const failedSnapshots = renderHook(() => useSnapshots(2))
    await waitFor(() => expect(failedSnapshots.result.current.isError).toBe(true))
  })

  it('loads sessions through pagination and details', async () => {
    api.sessionApi.list.mockResolvedValueOnce({ sessions: [{ id: 1 }], next_page_token: 'next' }).mockResolvedValueOnce({ sessions: [{ id: 2 }], next_page_token: null })
    const sessions = renderHook(() => useSessions())
    await waitFor(() => expect(sessions.result.current.data).toHaveLength(2))
    expect(cache.invalidateQueries).toHaveBeenCalledWith(['sessions'])
    api.sessionApi.getDetails.mockResolvedValue({ session_id: 1 })
    const details = renderHook(() => useSessionDetails(1))
    await waitFor(() => expect(details.result.current.data).toEqual({ session_id: 1 }))
    const noDetails = renderHook(() => useSessionDetails(null))
    expect(noDetails.result.current.isPending).toBe(false)
  })

  it('loads current session, handles notifications, and restores snapshots', async () => {
    const storage = new Map<string, string>([['comic_pile_last_session_id_7', '1']])
    Object.defineProperty(window, 'localStorage', { configurable: true, value: { getItem: (k: string) => storage.get(k) ?? null, setItem: (k: string, v: string) => storage.set(k, v) } })
    api.sessionApi.getCurrent.mockResolvedValue({ id: 2, user_id: 7 })
    const current = renderHook(() => useSession())
    await waitFor(() => expect(current.result.current.data?.id).toBe(2))
    expect(toast.showToast).toHaveBeenCalled()
    api.sessionApi.getSnapshots.mockResolvedValue({ snapshots: [] })
    const snapshots = renderHook(() => useSessionSnapshots(1))
    await waitFor(() => expect(snapshots.result.current.data).toEqual({ snapshots: [] }))
    api.sessionApi.restoreSessionStart.mockResolvedValue({ ok: true })
    const restore = renderHook(() => useRestoreSessionStart())
    await act(async () => await restore.result.current.mutate(1))
    expect(api.sessionApi.restoreSessionStart).toHaveBeenCalledWith(1)
    api.undoApi.undo.mockResolvedValue(undefined)
    const undo = renderHook(() => useUndo())
    await act(async () => await undo.result.current.mutate({ sessionId: 1, snapshotId: 2 }))

    api.undoApi.undo.mockRejectedValueOnce(new Error('undo failed'))
    const failedUndo = renderHook(() => useUndo())
    await act(async () => expect(failedUndo.result.current.mutate({ sessionId: 1, snapshotId: 2 })).rejects.toThrow('undo failed'))
  })

  it('covers session error and empty-id branches', async () => {
    api.sessionApi.getCurrent.mockRejectedValueOnce('bad session')
    const current = renderHook(() => useSession())
    await waitFor(() => expect(current.result.current.isError).toBe(true))
    expect(current.result.current.error?.message).toBe('Failed to fetch current session')

    api.sessionApi.list.mockRejectedValueOnce(new Error('list failed'))
    const sessions = renderHook(() => useSessions(null as never))
    await waitFor(() => expect(sessions.result.current.isError).toBe(true))
    api.sessionApi.getDetails.mockRejectedValueOnce('details failed')
    const details = renderHook(() => useSessionDetails(9))
    await waitFor(() => expect(details.result.current.isError).toBe(true))
    api.sessionApi.getSnapshots.mockRejectedValueOnce('snapshots failed')
    const snapshots = renderHook(() => useSessionSnapshots(9))
    await waitFor(() => expect(snapshots.result.current.isError).toBe(true))
    api.sessionApi.restoreSessionStart.mockRejectedValueOnce('restore failed')
    const restore = renderHook(() => useRestoreSessionStart())
    await act(async () => {
      await expect(restore.result.current.mutate(9)).rejects.toBe('restore failed')
    })
    await waitFor(() => expect(restore.result.current.isError).toBe(true))
  })

  it('covers storage fallbacks, unchanged sessions, empty snapshots, and Axios restore errors', async () => {
    const originalStorage = window.localStorage
    const storageFailure = {
      getItem: () => { throw new Error('storage unavailable') },
      setItem: () => { throw new Error('storage unavailable') },
    }
    Object.defineProperty(window, 'localStorage', { configurable: true, value: storageFailure })
    api.sessionApi.getCurrent.mockResolvedValueOnce({ id: 8 })
    const current = renderHook(() => useSession())
    await waitFor(() => expect(current.result.current.data?.id).toBe(8))
    expect(toast.showToast).not.toHaveBeenCalled()

    const emptySnapshots = renderHook(() => useSessionSnapshots(null))
    expect(emptySnapshots.result.current.isPending).toBe(false)
    const axiosError = new axios.AxiosError('restore request failed', 'ERR_BAD_REQUEST')
    axiosError.isAxiosError = true
    axiosError.response = { status: 400, data: { detail: 'server rejected restore' } } as never
    api.sessionApi.restoreSessionStart.mockRejectedValueOnce(axiosError)
    const restore = renderHook(() => useRestoreSessionStart())
    await act(async () => expect(restore.result.current.mutate(8)).rejects.toBe(axiosError))
    expect(restore.result.current.error).toBe(axiosError)
    Object.defineProperty(window, 'localStorage', { configurable: true, value: originalStorage })
  })

  it('ignores snapshots that resolve after unmount', async () => {
    let resolveSnapshots!: (value: unknown) => void
    api.undoApi.listSnapshots.mockImplementationOnce(() => new Promise((resolve) => { resolveSnapshots = resolve }))
    const snapshots = renderHook(() => useSnapshots(44))
    snapshots.unmount()
    await act(async () => resolveSnapshots({ snapshots: [{ id: 44 }] }))
  })
})
