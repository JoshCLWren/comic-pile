import { act, renderHook } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { useMoveToBack, useMoveToFront, useMoveToPosition } from '../hooks/useQueue'
import { queueApi } from '../services/api'

vi.mock('../services/api', () => ({
  queueApi: {
    moveToPosition: vi.fn(),
    moveToFront: vi.fn(),
    moveToBack: vi.fn(),
  },
}))

beforeEach(() => {
  queueApi.moveToPosition.mockResolvedValue({})
  queueApi.moveToFront.mockResolvedValue({})
  queueApi.moveToBack.mockResolvedValue({})
})

it('moves queue position', async () => {
  const { result } = renderHook(() => useMoveToPosition())

  await act(async () => {
    await result.current.mutate({ id: 4, position: 2 })
  })

  expect(queueApi.moveToPosition).toHaveBeenCalledWith(4, 2)
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

  expect(queueApi.moveToFront).toHaveBeenCalledWith(8)
  expect(queueApi.moveToBack).toHaveBeenCalledWith(9)
})
