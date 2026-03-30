import { act, renderHook, waitFor } from '@testing-library/react'
import { CacheProvider } from '../contexts/CacheContext'
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

const mockedThreadsApi = vi.mocked(threadsApi)

beforeEach(() => {
  mockedThreadsApi.list.mockResolvedValue({ threads: [{ id: 1 }], next_page_token: null } as never)
  mockedThreadsApi.get.mockResolvedValue({ id: 2 } as never)
  mockedThreadsApi.listStale.mockResolvedValue([{ id: 3 }] as never)
  mockedThreadsApi.create.mockResolvedValue({} as never)
  mockedThreadsApi.update.mockResolvedValue({} as never)
  mockedThreadsApi.delete.mockResolvedValue(undefined as never)
  mockedThreadsApi.reactivate.mockResolvedValue({} as never)
})

it('loads threads data', async () => {
  const { result } = renderHook(() => useThreads(), { wrapper: CacheProvider })

  await waitFor(() => expect(result.current.data).toEqual([{ id: 1 }]))
  expect(mockedThreadsApi.list).toHaveBeenCalled()
})

it('loads thread details and stale list', async () => {
  const { result: threadResult } = renderHook(() => useThread(2))
  const { result: staleResult } = renderHook(() => useStaleThreads(7))

  await waitFor(() => expect(threadResult.current.data).toEqual({ id: 2 }))
  await waitFor(() => expect(staleResult.current.data).toEqual([{ id: 3 }]))
  expect(mockedThreadsApi.get).toHaveBeenCalledWith(2)
  expect(mockedThreadsApi.listStale).toHaveBeenCalledWith(7)
})

it('creates, updates, deletes, and reactivates threads', async () => {
  const { result: createResult } = renderHook(() => useCreateThread())
  await act(async () => {
    await createResult.current.mutate({ title: 'New', format: 'Comics', issues_remaining: 5 })
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

  expect(mockedThreadsApi.create).toHaveBeenCalledWith({
    title: 'New',
    format: 'Comics',
    issues_remaining: 5,
  })
  expect(mockedThreadsApi.update).toHaveBeenCalledWith(7, { title: 'Updated' })
  expect(mockedThreadsApi.delete).toHaveBeenCalledWith(7)
  expect(mockedThreadsApi.reactivate).toHaveBeenCalledWith({ thread_id: 7, issues_to_add: 3 })
})
