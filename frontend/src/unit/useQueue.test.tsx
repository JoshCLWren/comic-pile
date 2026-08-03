import { act, renderHook } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import {
  useMoveToBack,
  useMoveToFront,
  useMoveToPosition,
  useShuffleQueue,
} from '../hooks/useQueue'
import { invalidateAfterQueueMovement } from '../query/cacheEffects'
import { queueApi } from '../services/api'

vi.mock('../services/api', () => ({
  queueApi: {
    moveToPosition: vi.fn(),
    moveToFront: vi.fn(),
    moveToBack: vi.fn(),
    shuffle: vi.fn(),
  },
}))

vi.mock('../query/cacheEffects', () => ({
  invalidateAfterQueueMovement: vi.fn(),
}))

const mockedQueueApi = vi.mocked(queueApi)
const mockedInvalidateAfterQueueMovement = vi.mocked(
  invalidateAfterQueueMovement,
)

beforeEach(() => {
  vi.clearAllMocks()
  mockedQueueApi.moveToPosition.mockResolvedValue(undefined as never)
  mockedQueueApi.moveToFront.mockResolvedValue(undefined as never)
  mockedQueueApi.moveToBack.mockResolvedValue(undefined as never)
  mockedQueueApi.shuffle.mockResolvedValue(undefined as never)
  mockedInvalidateAfterQueueMovement.mockResolvedValue(undefined)
})

it('moves queue position and reconciles retained queue owners', async () => {
  const { result } = renderHook(() => useMoveToPosition())

  await act(async () => {
    await result.current.mutate({ id: 4, position: 2 })
  })

  expect(mockedQueueApi.moveToPosition).toHaveBeenCalledWith(4, 2)
  expect(mockedInvalidateAfterQueueMovement).toHaveBeenCalledTimes(1)
})

it('moves thread to front and back and reconciles each successful movement', async () => {
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
})

it('shuffles the queue and reconciles retained queue owners', async () => {
  const { result } = renderHook(() => useShuffleQueue())

  await act(async () => {
    await result.current.mutate()
  })

  expect(mockedQueueApi.shuffle).toHaveBeenCalled()
  expect(mockedInvalidateAfterQueueMovement).toHaveBeenCalledTimes(1)
})

it('does not invalidate retained queue owners when the mutation fails', async () => {
  mockedQueueApi.moveToFront.mockRejectedValueOnce(new Error('move failed'))
  const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})
  const { result } = renderHook(() => useMoveToFront())

  await act(async () => {
    await expect(result.current.mutate(12)).rejects.toThrow('move failed')
  })

  expect(result.current.isError).toBe(true)
  expect(mockedInvalidateAfterQueueMovement).not.toHaveBeenCalled()
  consoleError.mockRestore()
})
