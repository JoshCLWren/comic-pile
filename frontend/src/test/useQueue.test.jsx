import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { useMoveToBack, useMoveToFront, useMoveToPosition } from '../hooks/useQueue'
import { queueApi } from '../services/api'
import { createQueryWrapper, createTestQueryClient } from './testUtils'

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

it('moves queue position and invalidates threads', async () => {
  const queryClient = createTestQueryClient()
  const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')
  const wrapper = createQueryWrapper(queryClient)
  const { result } = renderHook(() => useMoveToPosition(), { wrapper })

  await act(async () => {
    await result.current.mutateAsync({ id: 4, position: 2 })
  })

  expect(queueApi.moveToPosition).toHaveBeenCalledWith(4, 2)
  await waitFor(() => expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['threads'] }))
})

it('moves thread to front and back', async () => {
  const queryClient = createTestQueryClient()
  const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')
  const wrapper = createQueryWrapper(queryClient)

  const { result: frontResult } = renderHook(() => useMoveToFront(), { wrapper })
  await act(async () => {
    await frontResult.current.mutateAsync(8)
  })

  const { result: backResult } = renderHook(() => useMoveToBack(), { wrapper })
  await act(async () => {
    await backResult.current.mutateAsync(9)
  })

  expect(queueApi.moveToFront).toHaveBeenCalledWith(8)
  expect(queueApi.moveToBack).toHaveBeenCalledWith(9)
  await waitFor(() => expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['threads'] }))
})
