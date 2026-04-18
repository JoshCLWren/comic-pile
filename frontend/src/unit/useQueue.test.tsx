import { act, renderHook } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { useMoveToBack, useMoveToFront, useMoveToPosition, useShuffleQueue } from '../hooks/useQueue'
import { queueApi } from '../services/api'

vi.mock('../services/api', () => ({
  queueApi: {
    moveToPosition: vi.fn(),
    moveToFront: vi.fn(),
    moveToBack: vi.fn(),
    shuffle: vi.fn(),
  },
}))

const mockedQueueApi = vi.mocked(queueApi)

beforeEach(() => {
  mockedQueueApi.moveToPosition.mockResolvedValue(undefined as never)
  mockedQueueApi.moveToFront.mockResolvedValue(undefined as never)
  mockedQueueApi.moveToBack.mockResolvedValue(undefined as never)
  mockedQueueApi.shuffle.mockResolvedValue(undefined as never)
})

it('moves queue position', async () => {
  const { result } = renderHook(() => useMoveToPosition())

  await act(async () => {
    await result.current.mutate({ id: 4, position: 2 })
  })

  expect(mockedQueueApi.moveToPosition).toHaveBeenCalledWith(4, 2)
})

it('moves thread to front and back', async () => {
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
})

it('shuffles the queue', async () => {
  const { result } = renderHook(() => useShuffleQueue())

  await act(async () => {
    await result.current.mutate()
  })

  expect(mockedQueueApi.shuffle).toHaveBeenCalled()
})
