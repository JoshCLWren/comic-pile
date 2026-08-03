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

const mockedUndoApi = vi.mocked(undoApi)

beforeEach(() => {
  mockedUndoApi.listSnapshots.mockResolvedValue([{ id: 1 }] as never)
  mockedUndoApi.undo.mockResolvedValue(undefined as never)
})

it('loads undo snapshots', async () => {
  const { result } = renderHook(() => useSnapshots(5))

  await waitFor(() => expect(result.current.data).toEqual([{ id: 1 }]))
  expect(mockedUndoApi.listSnapshots).toHaveBeenCalledWith(5)
})

it('undoes snapshot', async () => {
  const { result } = renderHook(() => useUndo())

  await act(async () => {
    await result.current.mutate({ sessionId: 5, snapshotId: 2 })
  })

  expect(mockedUndoApi.undo).toHaveBeenCalledWith(5, 2)
})

it('handles snapshots load failure', async () => {
  mockedUndoApi.listSnapshots.mockRejectedValueOnce(new Error('undo list failed'))
  console.error = vi.fn()

  const { result } = renderHook(() => useSnapshots(7))

  await waitFor(() => expect(result.current.isError).toBe(true))
  expect(console.error).toHaveBeenCalledWith('Failed to load snapshots:', 'undo list failed')

  let rejectLate: (reason: unknown) => void
  mockedUndoApi.listSnapshots.mockReturnValueOnce(new Promise((_resolve, reject) => { rejectLate = reject }))
  const late = renderHook(() => useSnapshots(8))
  late.unmount()
  console.error = vi.fn()
  await act(async () => rejectLate!(new Error('late error')))
})

it('handles undo mutation failure', async () => {
  mockedUndoApi.undo.mockRejectedValueOnce(new Error('undo mutation failed'))
  console.error = vi.fn()

  const { result } = renderHook(() => useUndo())

  await act(async () => {
    await expect(result.current.mutate({ sessionId: 5, snapshotId: 2 })).rejects.toThrow('undo mutation failed')
  })

  expect(console.error).toHaveBeenCalledWith('Failed to undo action:', 'undo mutation failed')
  expect(result.current.isError).toBe(true)
})
