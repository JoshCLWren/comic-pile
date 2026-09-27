import { type ReactNode } from 'react'
import { act, renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, expect, it, vi } from 'vitest'
import { useSnapshots, useUndo } from '../hooks/useUndo'
import { undoApi } from '../services/api-undo'

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

vi.mock('../services/api-undo', () => ({
  undoApi: {
    listSnapshots: vi.fn(),
    undo: vi.fn(),
  },
}))

const mockedUndoApi = vi.mocked(undoApi)

beforeEach(() => {
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
})
