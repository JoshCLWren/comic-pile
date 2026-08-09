import { act, renderHook } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { useUpdateThread } from '../hooks/useThread'
import { applyUpdatedThreadCache } from '../query/cacheEffects'
import { queryClient } from '../query/queryClient'
import { threadsApi } from '../services/api'
import type { Thread } from '../types'

vi.mock('../services/api', () => ({
  threadsApi: {
    update: vi.fn(),
  },
}))

vi.mock('../query/cacheEffects', () => ({
  applyUpdatedThreadCache: vi.fn(),
}))

const mockedThreadsApi = vi.mocked(threadsApi)
const mockedApplyUpdatedThreadCache = vi.mocked(applyUpdatedThreadCache)

beforeEach(() => {
  mockedThreadsApi.update.mockReset()
  mockedApplyUpdatedThreadCache.mockReset()
  mockedApplyUpdatedThreadCache.mockResolvedValue(undefined)
})

it('publishes the authoritative update through the targeted thread-cache contract', async () => {
  const updatedThread = {
    id: 7,
    title: 'Updated title',
  } as Thread
  mockedThreadsApi.update.mockResolvedValue(updatedThread)

  const { result } = renderHook(() => useUpdateThread())

  let returnedThread: Thread | undefined
  await act(async () => {
    returnedThread = await result.current.mutate({
      id: 7,
      data: { title: 'Updated title' },
    })
  })

  expect(mockedThreadsApi.update).toHaveBeenCalledWith(7, { title: 'Updated title' })
  expect(mockedApplyUpdatedThreadCache).toHaveBeenCalledOnce()
  expect(mockedApplyUpdatedThreadCache).toHaveBeenCalledWith(queryClient, updatedThread)
  expect(returnedThread).toBe(updatedThread)
  expect(result.current.isError).toBe(false)
  expect(result.current.isPending).toBe(false)
})

it('does not touch targeted cache state when the update request fails', async () => {
  const failure = new Error('update failed')
  mockedThreadsApi.update.mockRejectedValue(failure)

  const { result } = renderHook(() => useUpdateThread())

  await expect(
    act(async () =>
      result.current.mutate({
        id: 7,
        data: { title: 'Never saved' },
      }),
    ),
  ).rejects.toBe(failure)

  expect(mockedApplyUpdatedThreadCache).not.toHaveBeenCalled()
  expect(result.current.isError).toBe(true)
  expect(result.current.isPending).toBe(false)
})
