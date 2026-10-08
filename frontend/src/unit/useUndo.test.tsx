import { type ReactNode } from 'react'
import { act, renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, expect, it, vi } from 'vitest'
import { useSnapshots, useUndo } from '../hooks/useUndo'
import { undoApi } from '../services/api-undo'
import { queryKeys } from '../query/queryKeys'
import { ToastProvider } from '../contexts/ToastProvider'

function createWrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return {
    client,
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>
        <ToastProvider>{children}</ToastProvider>
      </QueryClientProvider>
    ),
  }
}

function wrapper({ children }: { children: ReactNode }) {
  return createWrapper().wrapper({ children })
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

it('invalidates every projection a restore rewrites (#3194)', async () => {
  // #3194 reported both a Roll page that still rendered pre-undo state and a
  // History card whose "issues read" count still included the undone rating.
  // The History index, the session timeline, and the consumed snapshot list
  // live outside the queue-movement set, so each one is asserted explicitly.
  const { client, wrapper: localWrapper } = createWrapper()
  const invalidate = vi.spyOn(client, 'invalidateQueries')
  const reset = vi.spyOn(client, 'resetQueries')
  const { result } = renderHook(() => useUndo(), { wrapper: localWrapper })

  await act(async () => {
    await result.current.mutate({ sessionId: 5, snapshotId: 2 })
  })

  expect(reset.mock.calls.map(([filters]) => filters)).toEqual([
    { queryKey: queryKeys.queue.pages() },
  ])
  expect(invalidate.mock.calls.map(([filters]) => filters)).toEqual(
    expect.arrayContaining([
      { queryKey: queryKeys.session.current(), exact: true },
      { queryKey: queryKeys.roll.bootstrap(), exact: true },
      { queryKey: queryKeys.session.pages() },
      { queryKey: queryKeys.session.details() },
      { queryKey: queryKeys.session.snapshotLists() },
    ]),
  )
})
