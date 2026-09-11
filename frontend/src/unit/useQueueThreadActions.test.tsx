import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useDeleteThread } from '../hooks/useThread'
import {
  useMoveToBack,
  useMoveToFront,
  useMoveToPosition,
  useShuffleQueue,
} from '../hooks/useQueue'
import { useSnooze, useUnsnooze } from '../hooks/useSnooze'
import { useToast } from '../contexts/useToast'
import { threadsApi } from '../services/api'
import { queryClient as sharedQueryClient } from '../query/queryClient'
import { queryKeys } from '../query/queryKeys'
import { useQueueThreadActions } from '../pages/QueuePage/useQueueThreadActions'
import type { Thread } from '../types'

vi.mock('../hooks/useThread', () => ({
  useDeleteThread: vi.fn(),
}))

vi.mock('../hooks/useQueue', () => ({
  useMoveToBack: vi.fn(),
  useMoveToFront: vi.fn(),
  useMoveToPosition: vi.fn(),
  useShuffleQueue: vi.fn(),
}))

vi.mock('../hooks/useSnooze', () => ({
  useSnooze: vi.fn(),
  useUnsnooze: vi.fn(),
}))

vi.mock('../contexts/useToast', () => ({
  useToast: vi.fn(),
}))

vi.mock('../services/api', () => ({
  threadsApi: {
    setPending: vi.fn(),
  },
}))

const mockedDelete = vi.mocked(useDeleteThread)
const mockedMoveToFront = vi.mocked(useMoveToFront)
const mockedMoveToBack = vi.mocked(useMoveToBack)
const mockedMoveToPosition = vi.mocked(useMoveToPosition)
const mockedShuffle = vi.mocked(useShuffleQueue)
const mockedSnooze = vi.mocked(useSnooze)
const mockedUnsnooze = vi.mocked(useUnsnooze)
const mockedToast = vi.mocked(useToast)
const mockedSetPending = vi.mocked(threadsApi.setPending)
const toastSpy = vi.fn()

function mutationStubs() {
  return {
    mutate: vi.fn().mockResolvedValue(undefined),
    isPending: false,
    isError: false,
    retryRefresh: vi.fn().mockResolvedValue(true),
    refreshError: null,
    hasRefreshError: false,
  }
}

function makeThread(overrides: Partial<Thread>): Thread {
  return {
    id: 1,
    title: 'Saga',
    format: 'Comic',
    status: 'active',
    queue_position: 1,
    issues_remaining: 1,
    total_issues: null,
    is_blocked: false,
    blocking_reasons: [],
    created_at: '2024-01-01T00:00:00Z',
    ...overrides,
  }
}

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
})

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
}

beforeEach(() => {
  vi.clearAllMocks()
  sharedQueryClient.clear()
  vi.stubGlobal('alert', vi.fn())
  mockedToast.mockReturnValue({ showToast: toastSpy, removeToast: vi.fn(), toasts: [] })
  mockedDelete.mockReturnValue(mutationStubs())
  mockedMoveToFront.mockReturnValue(mutationStubs())
  mockedMoveToBack.mockReturnValue(mutationStubs())
  mockedMoveToPosition.mockReturnValue(mutationStubs())
  mockedShuffle.mockReturnValue(mutationStubs())
  mockedSnooze.mockReturnValue(mutationStubs())
  mockedUnsnooze.mockReturnValue(mutationStubs())
})

describe('useQueueThreadActions', () => {
  it('persists drag state across start, over, drop, and end', () => {
    const { result } = renderHook(
      () =>
        useQueueThreadActions({
          navigateToRoll: vi.fn(),
          refetchSession: vi.fn(),
        }),
      { wrapper },
    )

    // SAFETY: minimal drag-event objects satisfy the DragEvent shape exercised by the handlers
    act(() => result.current.handleDragStart(1)({ dataTransfer: { effectAllowed: '', setData: vi.fn() } } as never))
    expect(result.current.draggedThreadId).toBe(1)

    // SAFETY: minimal drag-event object satisfies the handler's expectation
    act(() => result.current.handleDragOver(2)({ preventDefault: vi.fn() } as never))
    expect(result.current.dragOverThreadId).toBe(2)

    act(() => result.current.handleDragEnd())
    expect(result.current.draggedThreadId).toBeNull()
    expect(result.current.dragOverThreadId).toBeNull()
  })

  it('moves to position using the target thread queue position', async () => {
    const movePosition = { mutate: vi.fn().mockResolvedValue(undefined), isPending: false, isError: false }
    mockedMoveToPosition.mockReturnValue(movePosition)
    const { result } = renderHook(
      () =>
        useQueueThreadActions({
          navigateToRoll: vi.fn(),
          refetchSession: vi.fn(),
        }),
      { wrapper },
    )

    // SAFETY: minimal drag-event objects satisfy the DragEvent shape exercised by the handlers
    act(() => result.current.handleDragStart(1)({ dataTransfer: { effectAllowed: '', setData: vi.fn() } } as never))
    act(() => result.current.handleDrop(2, [makeThread({ id: 1, queue_position: 5 }), makeThread({ id: 2, queue_position: 2 })])(
      // SAFETY: minimal drop-event object satisfies the handler's expectation
      { preventDefault: vi.fn() } as never,
    ))

    await waitFor(() => expect(movePosition.mutate).toHaveBeenCalledWith({ id: 1, position: 2 }))
  })

  it('reports move-to-position failures as a reorder error without crashing', async () => {
    const movePosition = { mutate: vi.fn().mockRejectedValue(new Error('reorder failed')), isPending: false, isError: false }
    mockedMoveToPosition.mockReturnValue(movePosition)
    const { result } = renderHook(
      () =>
        useQueueThreadActions({
          navigateToRoll: vi.fn(),
          refetchSession: vi.fn(),
        }),
      { wrapper },
    )

    // SAFETY: minimal drag-event objects satisfy the DragEvent shape exercised by the handlers
    act(() => result.current.handleDragStart(1)({ dataTransfer: { effectAllowed: '', setData: vi.fn() } } as never))
    act(() =>
      result.current.handleDrop(2, [makeThread({ id: 1, queue_position: 5 }), makeThread({ id: 2, queue_position: 2 })])(
        // SAFETY: minimal drop-event object satisfies the handler's expectation
        { preventDefault: vi.fn() } as never,
      ),
    )

    await waitFor(() => expect(result.current.reorderError).toBe('reorder failed'))
  })

  it('rejects read for blocked threads and routes allowed reads through setPending', async () => {
    mockedSetPending.mockResolvedValue({
    thread_id: 9,
    title: 'Test Thread',
    format: 'Comic',
    issues_remaining: 5,
    queue_position: 2,
    die_size: 6,
    result: 1,
    offset: 0,
    snoozed_count: 0,
    issue_id: null,
    issue_number: null,
    next_issue_id: null,
    next_issue_number: null,
    total_issues: null,
    reading_progress: null,
  })
    const navigate = vi.fn()
    const { result } = renderHook(
      () =>
        useQueueThreadActions({
          navigateToRoll: navigate,
          refetchSession: vi.fn(),
        }),
      { wrapper },
    )

    await result.current.handleThreadRead(makeThread({ id: 7, is_blocked: true }))
    expect(window.alert).not.toHaveBeenCalled()
    expect(navigate).not.toHaveBeenCalled()

    await result.current.handleThreadRead(makeThread({ id: 8 }))
    expect(mockedSetPending).toHaveBeenCalledWith(8)
    expect(navigate).toHaveBeenCalled()
  })

  it('drops the cached roll bootstrap before handing off to Roll (#2153)', async () => {
    const staleBootstrap = { session_id: 1, pending_thread_id: null, roll_pool: [] }
    sharedQueryClient.setQueryData(queryKeys.roll.bootstrap(), staleBootstrap)
    sharedQueryClient.setQueryData(queryKeys.session.current(), { id: 1, pending_thread_id: null })
    // SAFETY: minimal roll response satisfies the mock return type for setPending
    mockedSetPending.mockResolvedValue({ thread_id: 8, title: 'Saga' } as never)

    const callOrder: string[] = []
    const navigate = vi.fn(() => {
      callOrder.push('navigate')
      expect(sharedQueryClient.getQueryData(queryKeys.roll.bootstrap())).toBeUndefined()
    })
    const { result } = renderHook(
      () =>
        useQueueThreadActions({
          navigateToRoll: navigate,
          refetchSession: vi.fn(),
        }),
      { wrapper },
    )

    await result.current.handleThreadRead(makeThread({ id: 8 }))

    expect(navigate).toHaveBeenCalledTimes(1)
    expect(callOrder).toEqual(['navigate'])
    expect(sharedQueryClient.getQueryData(queryKeys.roll.bootstrap())).toBeUndefined()
    expect(
      sharedQueryClient.getQueryState(queryKeys.session.current())?.isInvalidated,
    ).toBe(true)
  })

  it('does not navigate to Roll when set-pending fails', async () => {
    mockedSetPending.mockRejectedValue(new Error('Thread 8 has no issues remaining'))
    const navigate = vi.fn()
    const { result } = renderHook(
      () =>
        useQueueThreadActions({
          navigateToRoll: navigate,
          refetchSession: vi.fn(),
        }),
      { wrapper },
    )

    await result.current.handleThreadRead(makeThread({ id: 8 }))

    expect(navigate).not.toHaveBeenCalled()
    expect(window.alert).toHaveBeenCalledWith(
      expect.stringContaining('Thread 8 has no issues remaining'),
    )
  })

  it('delegates snooze vs unsnooze based on the current snoozed state', async () => {
    const snooze = { mutate: vi.fn().mockResolvedValue(undefined), isPending: false, isError: false, retryRefresh: vi.fn().mockResolvedValue(true), refreshError: null, hasRefreshError: false }
    const unsnooze = { mutate: vi.fn().mockResolvedValue(undefined), isPending: false, isError: false }
    mockedSnooze.mockReturnValue(snooze)
    mockedUnsnooze.mockReturnValue(unsnooze)
    const refetchSession = vi.fn().mockResolvedValue(undefined)
    const { result } = renderHook(
      () =>
        useQueueThreadActions({
          navigateToRoll: vi.fn(),
          refetchSession,
        }),
      { wrapper },
    )

    await result.current.handleSnoozeToggle(makeThread({ id: 4 }), false)
    expect(snooze.mutate).toHaveBeenCalledWith(4)
    expect(refetchSession).toHaveBeenCalled()

    await result.current.handleSnoozeToggle(makeThread({ id: 4 }), true)
    expect(unsnooze.mutate).toHaveBeenCalledWith(4)
  })

  it('reports shuffle failure as an alert', async () => {
    mockedShuffle.mockReturnValue({ mutate: vi.fn().mockRejectedValue(new Error('shuffle failed')), isPending: false, isError: false })
    const { result } = renderHook(
      () =>
        useQueueThreadActions({
          navigateToRoll: vi.fn(),
          refetchSession: vi.fn(),
        }),
      { wrapper },
    )

    await result.current.handleShuffle()
    expect(window.alert).toHaveBeenCalledWith(expect.stringContaining('shuffle'))
  })

  it('validates reposition bounds before calling the mutation', async () => {
    const movePosition = { mutate: vi.fn().mockResolvedValue(undefined), isPending: false, isError: false }
    mockedMoveToPosition.mockReturnValue(movePosition)
    const { result } = renderHook(
      () =>
        useQueueThreadActions({
          navigateToRoll: vi.fn(),
          refetchSession: vi.fn(),
        }),
      { wrapper },
    )

    await result.current.handleReposition(1, 0, 2)
    await result.current.handleReposition(1, 3, 2)
    expect(movePosition.mutate).not.toHaveBeenCalled()
    expect(window.alert).toHaveBeenCalled()
  })

  it('opens and cancels the delete confirmation without mutating', async () => {
    const remove = { mutate: vi.fn().mockResolvedValue(undefined), isPending: false, isError: false }
    mockedDelete.mockReturnValue(remove)
    const { result } = renderHook(
      () =>
        useQueueThreadActions({
          navigateToRoll: vi.fn(),
          refetchSession: vi.fn(),
        }),
      { wrapper },
    )

    act(() => result.current.requestDelete(makeThread({ id: 3, title: 'Doomed' })))
    expect(result.current.pendingDeleteThread?.title).toBe('Doomed')
    expect(remove.mutate).not.toHaveBeenCalled()

    act(() => result.current.cancelDelete())
    expect(result.current.pendingDeleteThread).toBeNull()
    expect(remove.mutate).not.toHaveBeenCalled()
  })

  it('confirms delete, closes the dialog, and shows a success toast', async () => {
    const remove = { mutate: vi.fn().mockResolvedValue(undefined), isPending: false, isError: false }
    mockedDelete.mockReturnValue(remove)
    const { result } = renderHook(
      () =>
        useQueueThreadActions({
          navigateToRoll: vi.fn(),
          refetchSession: vi.fn(),
        }),
      { wrapper },
    )

    act(() => result.current.requestDelete(makeThread({ id: 4, title: 'Doomed' })))
    await act(() => result.current.confirmDelete())

    expect(remove.mutate).toHaveBeenCalledWith(4)
    expect(result.current.pendingDeleteThread).toBeNull()
    expect(result.current.deleteError).toBeNull()
    expect(toastSpy).toHaveBeenCalledWith('Deleted "Doomed"', 'success')
  })

  it('shows an actionable error toast and keeps the dialog open on delete failure', async () => {
    const remove = {
      mutate: vi.fn().mockRejectedValue(new Error('Cannot delete thread: has dependencies')),
      isPending: false,
      isError: false,
    }
    mockedDelete.mockReturnValue(remove)
    const { result } = renderHook(
      () =>
        useQueueThreadActions({
          navigateToRoll: vi.fn(),
          refetchSession: vi.fn(),
        }),
      { wrapper },
    )

    act(() => result.current.requestDelete(makeThread({ id: 5, title: 'Doomed' })))
    await act(() => result.current.confirmDelete())

    expect(remove.mutate).toHaveBeenCalledWith(5)
    expect(result.current.pendingDeleteThread?.id).toBe(5)
    expect(result.current.deleteError).toBe('Cannot delete thread: has dependencies')
    expect(toastSpy).toHaveBeenCalledWith(
      'Failed to delete series: Cannot delete thread: has dependencies',
      'error',
    )
  })
})
