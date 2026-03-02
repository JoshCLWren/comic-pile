import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { useSnapshots, useUndo } from '../hooks/useUndo'
import { undoApi } from '../services/api'

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
  const { result } = renderHook(() => useSnapshots(5))

  await waitFor(() => expect(result.current.data).toEqual([{ id: 1 }]))
  expect(undoApi.listSnapshots).toHaveBeenCalledWith(5)
})

it('undoes snapshot', async () => {
  const { result } = renderHook(() => useUndo())

  await act(async () => {
    await result.current.mutate({ sessionId: 5, snapshotId: 2 })
  })

  expect(undoApi.undo).toHaveBeenCalledWith(5, 2)
})
