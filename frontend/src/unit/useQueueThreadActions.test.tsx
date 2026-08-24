import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import {
  useMoveToBack,
  useMoveToFront,
  useMoveToPosition,
  useShuffleQueue,
} from '../hooks/useQueue'
import { useDeleteThread } from '../hooks/useThread'
import { useSnooze, useUnsnooze } from '../hooks/useSnooze'
import { threadsApi } from '../services/api'
import { useQueueThreadActions } from '../pages/QueuePage/useQueueThreadActions'
import type { Thread } from '../types'

vi.mock('../hooks/useQueue', () => ({
  useMoveToBack: vi.fn(),
  useMoveToFront: vi.fn(),
  useMoveToPosition: vi.fn(),
  useShuffleQueue: vi.fn(),
}))

vi.mock('../hooks/useThread', () => ({
  useDeleteThread: vi.fn(),
}))

vi.mock('../hooks/useSnooze', () => ({
  useSnooze: vi.fn(),
  useUnsnooze: vi.fn(),
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
const mockedSetPending = vi.mocked(threadsApi.setPending)

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

function wrapper({ children }: { children: ReactNode }) {
  return <>{children}</>
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.stubGlobal('alert', vi.fn())
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

    act(() => result.current.handleDragStart(1)({ dataTransfer: { effectAllowed: '', setData: vi.fn() } } as never))
    expect(result.current.draggedThreadId).toBe(1)

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

    act(() => result.current.handleDragStart(1)({ dataTransfer: { effectAllowed: '', setData: vi.fn() } } as never))
    act(() => result.current.handleDrop(2, [makeThread({ id: 1, queue_position: 5 }), makeThread({ id: 2, queue_position: 2 })])(
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

    act(() => result.current.handleDragStart(1)({ dataTransfer: { effectAllowed: '', setData: vi.fn() } } as never))
    act(() =>
      result.current.handleDrop(2, [makeThread({ id: 1, queue_position: 5 }), makeThread({ id: 2, queue_position: 2 })])(
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
    expect(window.alert).toHaveBeenCalled()
    expect(navigate).not.toHaveBeenCalled()

    await result.current.handleThreadRead(makeThread({ id: 8 }))
    expect(mockedSetPending).toHaveBeenCalledWith(8)
    expect(navigate).toHaveBeenCalled()
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
})
