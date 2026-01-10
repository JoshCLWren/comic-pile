import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { useSnapshots, useUndo } from '../hooks/useUndo'
import { undoApi } from '../services/api'
import { createQueryWrapper, createTestQueryClient } from './testUtils'

vi.mock('../services/api', () => ({
  undoApi: {
    listSnapshots: vi.fn(),
    undo: vi.fn(),
  },
}))

beforeEach(() => {
  undoApi.listSnapshots.mockResolvedValue([{ id: 1 }])
  undoApi.undo.mockResolvedValue({})
})

it('loads undo snapshots', async () => {
  const queryClient = createTestQueryClient()
  const wrapper = createQueryWrapper(queryClient)
  const { result } = renderHook(() => useSnapshots(5), { wrapper })

  await waitFor(() => expect(result.current.data).toEqual([{ id: 1 }]))
  expect(undoApi.listSnapshots).toHaveBeenCalledWith(5)
})

it('undoes snapshot and invalidates queries', async () => {
  const queryClient = createTestQueryClient()
  const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')
  const wrapper = createQueryWrapper(queryClient)
  const { result } = renderHook(() => useUndo(), { wrapper })

  await act(async () => {
    await result.current.mutateAsync({ sessionId: 5, snapshotId: 2 })
  })

  expect(undoApi.undo).toHaveBeenCalledWith(5, 2)
  await waitFor(() => expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['session'] }))
  await waitFor(() => expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['threads'] }))
  await waitFor(() => expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['sessions'] }))
})
