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

it('supports search/collection pagination, explicit refetch, empty ids, and failures', async () => {
  mockedThreadsApi.list
    .mockResolvedValueOnce({ threads: [{ id: 1 }], next_page_token: 'next' } as never)
    .mockResolvedValueOnce({ threads: [{ id: 2 }], next_page_token: null } as never)
  const { result } = renderHook(() => useThreads({ searchTerm: '  saga ', collectionId: 4 }), { wrapper: CacheProvider })
  await waitFor(() => expect(result.current.data).toHaveLength(2))
  expect(mockedThreadsApi.list).toHaveBeenCalledWith({ search: 'saga', collection_id: 4, page_size: 200 }, 'next')
  mockedThreadsApi.list.mockResolvedValueOnce({ threads: [{ id: 9 }], next_page_token: 'later' } as never)
  await act(async () => result.current.refetch('page'))
  expect(result.current.nextPageToken).toBe('later')

  const empty = renderHook(() => useThread(null))
  expect(empty.result.current.isPending).toBe(false)
  mockedThreadsApi.get.mockRejectedValueOnce(new Error('missing'))
  const failed = renderHook(() => useThread(9))
  await waitFor(() => expect(failed.result.current.isError).toBe(true))
  mockedThreadsApi.listStale.mockRejectedValueOnce(new Error('stale failed'))
  const stale = renderHook(() => useStaleThreads())
  await waitFor(() => expect(stale.result.current.isError).toBe(true))
  mockedThreadsApi.listStale.mockResolvedValueOnce([] as never)
  await act(async () => stale.result.current.refetch())
})

it('marks all thread mutations as errors and resets pending state', async () => {
  mockedThreadsApi.create.mockRejectedValueOnce(new Error('create failed'))
  mockedThreadsApi.update.mockRejectedValueOnce(new Error('update failed'))
  mockedThreadsApi.delete.mockRejectedValueOnce(new Error('delete failed'))
  mockedThreadsApi.reactivate.mockRejectedValueOnce(new Error('reactivate failed'))
  const cases = [
    [useCreateThread, { title: 'x', format: 'Comic', issues_remaining: 1 }],
    [useUpdateThread, { id: 1, data: { title: 'x' } }],
    [useDeleteThread, 1],
    [useReactivateThread, { thread_id: 1, issues_to_add: 1 }],
  ] as const
  for (const [hook, payload] of cases) {
    const { result } = renderHook(() => hook())
    await expect(act(async () => result.current.mutate(payload as never))).rejects.toThrow()
    expect(result.current.isPending).toBe(false)
  }
})
