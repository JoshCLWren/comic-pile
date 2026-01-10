import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { useSettings, useUpdateSettings } from '../hooks/useSettings'
import { settingsApi } from '../services/api'
import { createQueryWrapper, createTestQueryClient } from './testUtils'

vi.mock('../services/api', () => ({
  settingsApi: {
    get: vi.fn(),
    update: vi.fn(),
  },
}))

beforeEach(() => {
  settingsApi.get.mockResolvedValue({ start_die: 8 })
  settingsApi.update.mockResolvedValue({})
})

it('loads settings', async () => {
  const queryClient = createTestQueryClient()
  const wrapper = createQueryWrapper(queryClient)
  const { result } = renderHook(() => useSettings(), { wrapper })

  await waitFor(() => expect(result.current.data).toEqual({ start_die: 8 }))
  expect(settingsApi.get).toHaveBeenCalled()
})

it('updates settings and invalidates cache', async () => {
  const queryClient = createTestQueryClient()
  const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')
  const wrapper = createQueryWrapper(queryClient)
  const { result } = renderHook(() => useUpdateSettings(), { wrapper })

  await act(async () => {
    await result.current.mutateAsync({ start_die: 10 })
  })

  expect(settingsApi.update).toHaveBeenCalledWith({ start_die: 10 })
  await waitFor(() => expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['settings'] }))
})
