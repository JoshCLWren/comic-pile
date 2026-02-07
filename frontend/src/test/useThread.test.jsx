import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import {
  useCreateThread,
  useDeleteThread,
  useReactivateThread,
  useStaleThreads,
  useThread,
  useThreads,
  useUpdateThread,
} from '../hooks/useThread'
import { threadsApi } from '../services/api'

vi.mock('../services/api', () => ({
  threadsApi: {
    list: vi.fn(),
    get: vi.fn(),
    listStale: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
    reactivate: vi.fn(),
  },
}))

beforeEach(() => {
  threadsApi.list.mockResolvedValue([{ id: 1 }])
  threadsApi.get.mockResolvedValue({ id: 2 })
  threadsApi.listStale.mockResolvedValue([{ id: 3 }])
  threadsApi.create.mockResolvedValue({})
  threadsApi.update.mockResolvedValue({})
  threadsApi.delete.mockResolvedValue({})
  threadsApi.reactivate.mockResolvedValue({})
})

it('loads threads data', async () => {
  const { result } = renderHook(() => useThreads())

  await waitFor(() => expect(result.current.data).toEqual([{ id: 1 }]))
  expect(threadsApi.list).toHaveBeenCalled()
})

it('loads thread details and stale list', async () => {
  const { result: threadResult } = renderHook(() => useThread(2))
  const { result: staleResult } = renderHook(() => useStaleThreads(7))

  await waitFor(() => expect(threadResult.current.data).toEqual({ id: 2 }))
  await waitFor(() => expect(staleResult.current.data).toEqual([{ id: 3 }]))
  expect(threadsApi.get).toHaveBeenCalledWith(2)
  expect(threadsApi.listStale).toHaveBeenCalledWith(7)
})

it('creates, updates, deletes, and reactivates threads', async () => {
  const { result: createResult } = renderHook(() => useCreateThread())
  await act(async () => {
    await createResult.current.mutate({ title: 'New' })
  })

  const { result: updateResult } = renderHook(() => useUpdateThread())
  await act(async () => {
    await updateResult.current.mutate({ id: 7, data: { title: 'Updated' } })
  })

  const { result: deleteResult } = renderHook(() => useDeleteThread())
  await act(async () => {
    await deleteResult.current.mutate(7)
  })

  const { result: reactivateResult } = renderHook(() => useReactivateThread())
  await act(async () => {
    await reactivateResult.current.mutate({ thread_id: 7, issues_to_add: 3 })
  })

  expect(threadsApi.create).toHaveBeenCalledWith({ title: 'New' })
  expect(threadsApi.update).toHaveBeenCalledWith(7, { title: 'Updated' })
  expect(threadsApi.delete).toHaveBeenCalledWith(7)
  expect(threadsApi.reactivate).toHaveBeenCalledWith({ thread_id: 7, issues_to_add: 3 })
})
