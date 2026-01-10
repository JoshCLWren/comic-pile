import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { useRate } from '../hooks/useRate'
import { rateApi } from '../services/api'
import { createQueryWrapper, createTestQueryClient } from './testUtils'

vi.mock('../services/api', () => ({
  rateApi: {
    rate: vi.fn(),
  },
}))

beforeEach(() => {
  rateApi.rate.mockResolvedValue({})
})

it('submits ratings and invalidates queries', async () => {
  const queryClient = createTestQueryClient()
  const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')
  const wrapper = createQueryWrapper(queryClient)
  const { result } = renderHook(() => useRate(), { wrapper })

  await act(async () => {
    await result.current.mutateAsync({ rating: 4 })
  })

  expect(rateApi.rate).toHaveBeenCalledWith({ rating: 4 })
  await waitFor(() => expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['session'] }))
  await waitFor(() => expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['threads'] }))
})
