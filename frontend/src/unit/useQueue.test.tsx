import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useQueueThreads, useMoveToBack, useMoveToFront, useMoveToPosition, useShuffleQueue } from '../hooks/useQueue'
import { invalidateAfterQueueMovement } from '../query/cacheEffects'
import { queryClient } from '../query/queryClient'
import { queueApi, threadsApi } from '../services/api'

vi.mock('../services/api', () => ({
  queueApi: {
    moveToPosition: vi.fn(),
    moveToFront: vi.fn(),
    moveToBack: vi.fn(),
    shuffle: vi.fn(),
  },
  threadsApi: {
    list: vi.fn(),
  },
}))

vi.mock('../query/cacheEffects', () => ({
  invalidateAfterQueueMovement: vi.fn(),
}))

const mockedQueueApi = vi.mocked(queueApi)
const mockedThreadsApi = vi.mocked(threadsApi)
const mockedInvalidateAfterQueueMovement = vi.mocked(invalidateAfterQueueMovement)

beforeEach(() => {
  vi.clearAllMocks()
  mockedQueueApi.moveToPosition.mockResolvedValue(undefined as never)
  mockedQueueApi.moveToFront.mockResolvedValue(undefined as never)
  mockedQueueApi.moveToBack.mockResolvedValue(undefined as never)
  mockedQueueApi.shuffle.mockResolvedValue(undefined as never)
  mockedInvalidateAfterQueueMovement.mockResolvedValue()
  mockedThreadsApi.list.mockResolvedValue({ threads: [], next_page_token: null })
})

describe('useQueueThreads', () => {
  it('fetches threads on mount with default page_size', async () => {
    const { result } = renderHook(() => useQueueThreads())

    await waitFor(() => expect(result.current.isPending).toBe(false))

    expect(mockedThreadsApi.list).toHaveBeenCalledWith(
      expect.objectContaining({ page_size: 50 }),
      undefined,
    )
    expect(result.current.data).toEqual([])
    expect(result.current.nextPageToken).toBeNull()
  })

  it('passes search term when provided', async () => {
    mockedThreadsApi.list.mockResolvedValue({
      threads: [{ id: 1, title: 'Bat' } as never],
      next_page_token: null,
    })

    const { result } = renderHook(() => useQueueThreads('bat'))

    await waitFor(() => expect(result.current.isPending).toBe(false))

    expect(mockedThreadsApi.list).toHaveBeenCalledWith(
      expect.objectContaining({ search: 'bat', page_size: 50 }),
      undefined,
    )
    expect(result.current.data).toHaveLength(1)
  })

  it('does not include page_size when pageToken is supplied', async () => {
    const { result } = renderHook(() => useQueueThreads())

    await waitFor(() => expect(result.current.isPending).toBe(false))

    mockedThreadsApi.list.mockResolvedValue({
      threads: [{ id: 2 } as never],
      next_page_token: null,
    })

    await act(async () => {
      await result.current.refetch('next-page')
    })

    expect(mockedThreadsApi.list).toHaveBeenLastCalledWith(undefined, 'next-page')
  })

  it('sets error state when API call fails', async () => {
    mockedThreadsApi.list.mockRejectedValueOnce(new Error('network'))

    const { result } = renderHook(() => useQueueThreads())

    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(result.current.isPending).toBe(false)
  })

  it('loadMore fetches next page when token exists', async () => {
    mockedThreadsApi.list
      .mockResolvedValueOnce({
        threads: [{ id: 1 } as never],
        next_page_token: 'tok-2',
      })
      .mockResolvedValueOnce({
        threads: [{ id: 2 } as never],
        next_page_token: null,
      })

    const { result } = renderHook(() => useQueueThreads())

    await waitFor(() => expect(result.current.isPending).toBe(false))

    await act(async () => {
      await result.current.loadMore()
    })

    expect(mockedThreadsApi.list).toHaveBeenCalledTimes(2)
    expect(result.current.data).toHaveLength(2)
  })

  it('loadMore is no-op when no next page token', async () => {
    const { result } = renderHook(() => useQueueThreads())

    await waitFor(() => expect(result.current.isPending).toBe(false))

    await act(async () => {
      await result.current.loadMore()
    })

    expect(mockedThreadsApi.list).toHaveBeenCalledTimes(1)
  })
})

it('moves queue position and reconciles only queue-owned read models', async () => {
  const { result } = renderHook(() => useMoveToPosition())

  await act(async () => {
    await result.current.mutate({ id: 4, position: 2 })
  })

  expect(mockedQueueApi.moveToPosition).toHaveBeenCalledWith(4, 2)
  expect(mockedInvalidateAfterQueueMovement).toHaveBeenCalledWith(queryClient)
})

it('moves thread to front and back and reconciles after each mutation', async () => {
  const { result: frontResult } = renderHook(() => useMoveToFront())
  await act(async () => {
    await frontResult.current.mutate(8)
  })

  const { result: backResult } = renderHook(() => useMoveToBack())
  await act(async () => {
    await backResult.current.mutate(9)
  })

  expect(mockedQueueApi.moveToFront).toHaveBeenCalledWith(8)
  expect(mockedQueueApi.moveToBack).toHaveBeenCalledWith(9)
  expect(mockedInvalidateAfterQueueMovement).toHaveBeenCalledTimes(2)
  expect(mockedInvalidateAfterQueueMovement).toHaveBeenNthCalledWith(1, queryClient)
  expect(mockedInvalidateAfterQueueMovement).toHaveBeenNthCalledWith(2, queryClient)
})

it('shuffles the queue and reconciles queue-owned read models', async () => {
  const { result } = renderHook(() => useShuffleQueue())

  await act(async () => {
    await result.current.mutate()
  })

  expect(mockedQueueApi.shuffle).toHaveBeenCalled()
  expect(mockedInvalidateAfterQueueMovement).toHaveBeenCalledWith(queryClient)
})

it('does not invalidate cache when a queue mutation fails', async () => {
  mockedQueueApi.moveToFront.mockRejectedValueOnce(new Error('move failed'))
  const { result } = renderHook(() => useMoveToFront())

  await expect(
    act(async () => {
      await result.current.mutate(8)
    }),
  ).rejects.toThrow('move failed')

  expect(mockedInvalidateAfterQueueMovement).not.toHaveBeenCalled()
})
