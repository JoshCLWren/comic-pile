import { type ReactNode } from 'react'
import { act, renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, expect, it, vi } from 'vitest'
import { useSnapshots, useUndo, useUndoLatestRating } from '../hooks/useUndo'
import { undoApi } from '../services/api-undo'
import { ToastContextSpy } from './toastTestHarness'
import { createToastSpy } from './toastSpy'

const toast = createToastSpy()

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return (
    <QueryClientProvider client={client}>
      <ToastContextSpy value={toast}>{children}</ToastContextSpy>
    </QueryClientProvider>
  )
}

vi.mock('../services/api-undo', () => ({
  undoApi: {
    listSnapshots: vi.fn(),
    undo: vi.fn(),
  },
}))

const mockedUndoApi = vi.mocked(undoApi)

beforeEach(() => {
  vi.clearAllMocks()
  // SAFETY: mock payload supplies only the fields this test asserts
  mockedUndoApi.listSnapshots.mockResolvedValue([{ id: 1 }] as never)
  // SAFETY: the endpoint returns no body, so the mock resolves to undefined
  mockedUndoApi.undo.mockResolvedValue(undefined as never)
})

it('loads undo snapshots', async () => {
  const { result } = renderHook(() => useSnapshots(5), { wrapper })

  await waitFor(() => expect(result.current.data).toEqual([{ id: 1 }]))
  expect(mockedUndoApi.listSnapshots).toHaveBeenCalledWith(5)
})

it('undoes snapshot', async () => {
  const { result } = renderHook(() => useUndo(), { wrapper })

  await act(async () => {
    await result.current.mutate({ sessionId: 5, snapshotId: 2 })
  })

  expect(mockedUndoApi.undo).toHaveBeenCalledWith(5, 2)
  expect(toast.showToast).toHaveBeenCalledWith(
    'Rating undone. Roll and History are up to date.',
    'success',
  )
})

it('reports undo failures without swallowing the error', async () => {
  mockedUndoApi.undo.mockRejectedValueOnce(new Error('undo failed'))
  const { result } = renderHook(() => useUndo(), { wrapper })

  await act(async () => {
    await expect(result.current.mutate({ sessionId: 5, snapshotId: 2 })).rejects.toThrow(
      'undo failed',
    )
  })

  expect(toast.showToast).toHaveBeenCalledWith('Undo failed. Nothing was changed.', 'error')
})

it('undoes the latest rating snapshot for a session', async () => {
  mockedUndoApi.listSnapshots.mockResolvedValue({
    snapshots: [
      { id: 9, description: 'Before rating', created_at: '2024-05-01T10:20:00Z' },
      { id: 8, description: 'Session start', created_at: '2024-05-01T10:00:00Z' },
    ],
  } as never)
  const { result } = renderHook(() => useUndoLatestRating(), { wrapper })

  let undone = false
  await act(async () => {
    undone = await result.current.undoLatest(12)
  })

  expect(undone).toBe(true)
  expect(mockedUndoApi.undo).toHaveBeenCalledWith(12, 9)
  expect(toast.showToast).toHaveBeenCalledWith(
    'Rating undone. Roll and History are up to date.',
    'success',
  )
})

it('does not call undo when no rating snapshot remains', async () => {
  mockedUndoApi.listSnapshots.mockResolvedValue({
    snapshots: [{ id: 8, description: 'Session start', created_at: '2024-05-01T10:00:00Z' }],
  } as never)
  const { result } = renderHook(() => useUndoLatestRating(), { wrapper })

  let undone = true
  await act(async () => {
    undone = await result.current.undoLatest(12)
  })

  expect(undone).toBe(false)
  expect(mockedUndoApi.undo).not.toHaveBeenCalled()
  expect(toast.showToast).toHaveBeenCalledWith(
    'Nothing to undo — the latest rating was already undone.',
    'info',
  )
})
