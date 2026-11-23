import { act, renderHook, waitFor } from './testingLibrary'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'

const navigateSpy = vi.fn()
import { useQueueThreadActions } from '../pages/QueuePage/useQueueThreadActions'
import type { UseQueueThreadActionsDeps } from '../pages/QueuePage/useQueueThreadActions'
import { queryClient as sharedQueryClient } from '../query/queryClient'
import { queryKeys } from '../query/queryKeys'
import type { Thread } from '../types'
import { NavigationSpy } from './routerTestHarness'

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
    last_activity_at: null,
    last_rating: null,
    notes: null,
    is_test: false,
    created_at: '2024-01-01T00:00:00Z',
    ...overrides,
  }
}

// Injectable seams passed through the real `useQueueThreadActions` second
// argument — no module mocking of the hooks or API services.
function buildDeps(overrides: Partial<UseQueueThreadActionsDeps> = {}): UseQueueThreadActionsDeps {
  return {
    deleteHook: () => mutationStubs(),
    moveToFrontHook: () => mutationStubs(),
    moveToBackHook: () => mutationStubs(),
    moveToPositionHook: () => mutationStubs(),
    shuffleHook: () => mutationStubs(),
    reroll: vi.fn().mockResolvedValue({ thread_id: 5, title: 'Next Comic' }),
    toastHook: () => ({ showToast: toastSpy, removeToast: vi.fn(), toasts: [] }),
    ...overrides,
  }
}

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
})

function wrapper({ children }: { children: ReactNode }) {
  return (
    <MemoryRouter>
      <NavigationSpy navigate={navigateSpy} />
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    </MemoryRouter>
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  sharedQueryClient.clear()
  globalThis.document.cookie = 'comicpile_roll_snoozes=; expires=Thu, 01 Jan 1970 00:00:00 GMT'
})

describe('useQueueThreadActions', () => {
  it('persists drag state across start, over, drop, and end', () => {
    const { result } = renderHook(
      () =>
        useQueueThreadActions(
          {
            restoreSeriesActionsFocus: vi.fn(),
          },
          buildDeps(),
        ),
      { wrapper },
    )

    // SAFETY: the drag-start handler reads only the stubbed dataTransfer members
    act(() => result.current.handleDragStart(1)({ dataTransfer: { effectAllowed: '', setData: vi.fn() } } as never))
    expect(result.current.draggedThreadId).toBe(1)

    // SAFETY: the drag handler reads only the stubbed preventDefault member
    act(() => result.current.handleDragOver(2)({ preventDefault: vi.fn() } as never))
    expect(result.current.dragOverThreadId).toBe(2)

    act(() => result.current.handleDragEnd())
    expect(result.current.draggedThreadId).toBeNull()
    expect(result.current.dragOverThreadId).toBeNull()
  })

  it('moves to position using the target thread queue position', async () => {
    const movePosition = { mutate: vi.fn().mockResolvedValue(undefined), isPending: false, isError: false }
    const { result } = renderHook(
      () =>
        useQueueThreadActions(
          {
            restoreSeriesActionsFocus: vi.fn(),
          },
          buildDeps({ moveToPositionHook: () => movePosition }),
        ),
      { wrapper },
    )

    // SAFETY: the drag-start handler reads only the stubbed dataTransfer members
    act(() => result.current.handleDragStart(1)({ dataTransfer: { effectAllowed: '', setData: vi.fn() } } as never))
    act(() => result.current.handleDrop(2, [makeThread({ id: 1, queue_position: 5 }), makeThread({ id: 2, queue_position: 2 })])(
      // SAFETY: the drag handler reads only the stubbed preventDefault member
      { preventDefault: vi.fn() } as never,
    ))

    await waitFor(() => expect(movePosition.mutate).toHaveBeenCalledWith({ id: 1, position: 2 }))
  })

  it('reports move-to-position failures as a reorder error without crashing', async () => {
    const movePosition = { mutate: vi.fn().mockRejectedValue(new Error('reorder failed')), isPending: false, isError: false }
    const { result } = renderHook(
      () =>
        useQueueThreadActions(
          {
            restoreSeriesActionsFocus: vi.fn(),
          },
          buildDeps({ moveToPositionHook: () => movePosition }),
        ),
      { wrapper },
    )

    // SAFETY: the drag-start handler reads only the stubbed dataTransfer members
    act(() => result.current.handleDragStart(1)({ dataTransfer: { effectAllowed: '', setData: vi.fn() } } as never))
    act(() =>
      result.current.handleDrop(2, [makeThread({ id: 1, queue_position: 5 }), makeThread({ id: 2, queue_position: 2 })])(
        // SAFETY: the drag handler reads only the stubbed preventDefault member
        { preventDefault: vi.fn() } as never,
      ),
    )

    await waitFor(() => expect(result.current.reorderError).toBe('reorder failed'))
  })

  it('routes Queue snooze to the native Rust reroll and unsnooze is client-side only (#4589)', async () => {
    const reroll = vi.fn().mockResolvedValue({ thread_id: 5, title: 'Next Comic' })
    const { result } = renderHook(
      () =>
        useQueueThreadActions(
          { restoreSeriesActionsFocus: vi.fn() },
          buildDeps({ reroll }),
        ),
      { wrapper },
    )

    await result.current.handleSnoozeToggle(makeThread({ id: 4, title: 'Pending Comic' }), false)
    expect(reroll).toHaveBeenCalledExactlyOnceWith(4)
    expect(toastSpy).toHaveBeenCalledWith(
      'Snoozed "Pending Comic" and rolled "Next Comic". Open Roll to read it.',
      'success',
    )

    // Unsnooze is now client-only (removes from browser cookie), no server call
    await result.current.handleSnoozeToggle(makeThread({ id: 4 }), true)
    expect(reroll).toHaveBeenCalledTimes(1)
  })

  it('refreshes current session once after native Queue reroll (#4589)', async () => {
    // Unlike legacy snooze, Rust reroll does not refresh the session query.
    sharedQueryClient.setQueryData(queryKeys.session.current(), {
      id: 1,
      pending_thread_id: 4,
    })
    const reroll = vi.fn().mockResolvedValue({ thread_id: 5, title: 'Next Comic' })
    const { result } = renderHook(
      () =>
        useQueueThreadActions(
          { restoreSeriesActionsFocus: vi.fn() },
          buildDeps({ reroll }),
        ),
      { wrapper },
    )

    await result.current.handleSnoozeToggle(makeThread({ id: 4 }), false)

    expect(reroll).toHaveBeenCalledExactlyOnceWith(4)
    expect(sharedQueryClient.getQueryState(queryKeys.session.current())?.isInvalidated).toBe(true)
  })

  it('does not repeat the owning legacy unsnooze session refresh (#4276)', async () => {
    sharedQueryClient.setQueryData(queryKeys.session.current(), {
      id: 1,
      snoozed_threads: [{ id: 4, title: 'Pending Comic' }],
    })
    const { result } = renderHook(
      () =>
        useQueueThreadActions(
          { restoreSeriesActionsFocus: vi.fn() },
          buildDeps(),
        ),
      { wrapper },
    )

    await result.current.handleSnoozeToggle(makeThread({ id: 4 }), true)

    expect(sharedQueryClient.getQueryState(queryKeys.session.current())?.isInvalidated).toBe(false)
  })

  it('exposes a shuffle failure for the open confirmation instead of a hidden toast', async () => {
    const { result } = renderHook(
      () =>
        useQueueThreadActions(
          {
            restoreSeriesActionsFocus: vi.fn(),
          },
          buildDeps({
            shuffleHook: () => ({ mutate: vi.fn().mockRejectedValue(new Error('shuffle failed')), isPending: false, isError: false }),
          }),
        ),
      { wrapper },
    )

    act(() => result.current.requestShuffle())
    await act(() => result.current.confirmShuffle())
    // The dialog stays open, so the failure must be dialog state; the shared
    // toast paints below the modal layer and is invisible on mobile.
    expect(result.current.shuffleError).toBe('Failed to shuffle queue. Please try again.')
    expect(toastSpy).not.toHaveBeenCalled()
    expect(result.current.isShuffleConfirmOpen).toBe(true)
  })

  it('clears the shuffle failure when the confirmation reopens', async () => {
    const { result } = renderHook(
      () =>
        useQueueThreadActions(
          {
            restoreSeriesActionsFocus: vi.fn(),
          },
          buildDeps({
            shuffleHook: () => ({ mutate: vi.fn().mockRejectedValue(new Error('shuffle failed')), isPending: false, isError: false }),
          }),
        ),
      { wrapper },
    )

    act(() => result.current.requestShuffle())
    await act(() => result.current.confirmShuffle())
    expect(result.current.shuffleError).not.toBeNull()

    act(() => result.current.cancelShuffle())
    expect(result.current.shuffleError).toBeNull()

    act(() => result.current.requestShuffle())
    expect(result.current.isShuffleConfirmOpen).toBe(true)
    expect(result.current.shuffleError).toBeNull()
  })

  it('gates the queue shuffle behind a confirmation that cancels without mutating', async () => {
    const shuffle = { mutate: vi.fn().mockResolvedValue(undefined), isPending: false, isError: false }
    const { result } = renderHook(
      () =>
        useQueueThreadActions(
          {
            restoreSeriesActionsFocus: vi.fn(),
          },
          buildDeps({ shuffleHook: () => shuffle }),
        ),
      { wrapper },
    )

    act(() => result.current.requestShuffle())
    expect(result.current.isShuffleConfirmOpen).toBe(true)
    expect(shuffle.mutate).not.toHaveBeenCalled()

    act(() => result.current.cancelShuffle())
    expect(result.current.isShuffleConfirmOpen).toBe(false)
    expect(shuffle.mutate).not.toHaveBeenCalled()

    act(() => result.current.requestShuffle())
    await act(() => result.current.confirmShuffle())
    expect(shuffle.mutate).toHaveBeenCalledTimes(1)
    expect(result.current.isShuffleConfirmOpen).toBe(false)
  })

  it('validates reposition bounds before calling the mutation', async () => {
    const movePosition = { mutate: vi.fn().mockResolvedValue(undefined), isPending: false, isError: false }
    const { result } = renderHook(
      () =>
        useQueueThreadActions(
          {
            restoreSeriesActionsFocus: vi.fn(),
          },
          buildDeps({ moveToPositionHook: () => movePosition }),
        ),
      { wrapper },
    )

    await result.current.handleReposition(1, 0, 2)
    await result.current.handleReposition(1, 3, 2)
    expect(movePosition.mutate).not.toHaveBeenCalled()
    expect(toastSpy).toHaveBeenCalled()
  })

  it('opens and cancels the delete confirmation without mutating', async () => {
    const remove = { mutate: vi.fn().mockResolvedValue(undefined), isPending: false, isError: false }
    const { result } = renderHook(
      () =>
        useQueueThreadActions(
          {
            restoreSeriesActionsFocus: vi.fn(),
          },
          buildDeps({ deleteHook: () => remove }),
        ),
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
    const { result } = renderHook(
      () =>
        useQueueThreadActions(
          {
            restoreSeriesActionsFocus: vi.fn(),
          },
          buildDeps({ deleteHook: () => remove }),
        ),
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
    const { result } = renderHook(
      () =>
        useQueueThreadActions(
          {
            restoreSeriesActionsFocus: vi.fn(),
          },
          buildDeps({ deleteHook: () => remove }),
        ),
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
