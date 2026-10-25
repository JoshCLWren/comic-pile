import { renderHook, act } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { useRollActions } from '../pages/RollPage/useRollActions'

describe('useRollActions snooze', () => {
  it('does not refetch bootstrap after successful snooze via action sheet', async () => {
    const setSelectedThread = vi.fn()
    const setIsActionSheetOpen = vi.fn()
    const state = {
      suppressPendingAutoOpenRef: { current: false },
      selectedThread: { id: 10 },
      setSelectedThread,
      setIsActionSheetOpen,
      setIsSetCurrentIssueOpen: vi.fn(),
      setIsShuffleOpen: vi.fn(),
      setErrorMessage: vi.fn(),
      setCurrentDie: vi.fn(),
      setThreadToMigrate: vi.fn(),
      setShowMigrationDialog: vi.fn(),
      setIsRolling: vi.fn(),
      setDiceState: vi.fn(),
      rollIntervalRef: { current: null },
      rollTimeoutRef: { current: null },
      staleThread: null,
    }

    const snoozeMutation = {
      mutate: vi.fn().mockResolvedValue(undefined),
      isPending: false,
    }

    const mutations = {
      setDieMutation: { mutate: vi.fn(), isPending: false },
      clearManualDieMutation: { mutate: vi.fn(), isPending: false },
      rollMutation: { mutate: vi.fn(), isPending: false },
      snoozeMutation,
      unsnoozeMutation: { mutate: vi.fn(), isPending: false },
      skipMutation: { mutate: vi.fn(), isPending: false },
      unskipMutation: { mutate: vi.fn(), isPending: false },
      moveToFrontMutation: { mutate: vi.fn(), isPending: false },
      moveToBackMutation: { mutate: vi.fn(), isPending: false },
      shuffleQueueMutation: { mutate: vi.fn(), isPending: false },
    }

    const refetchBootstrap = vi.fn().mockResolvedValue({})

    const { result } = renderHook(() =>
      useRollActions({
        state: state as any,
        bootstrap: { pending_thread_id: 10, snoozed_threads: [] } as any,
        rollPool: [],
        navigate: vi.fn(),
        mutations,
        refetchBootstrap,
        enterRatingView: vi.fn(),
        threadsApi: { setPending: vi.fn() } as any,
      })
    )

    await act(async () => {
      await result.current.handleAction('snooze')
    })

    expect(snoozeMutation.mutate).toHaveBeenCalledWith(10)
    // should not trigger an extra bootstrap fetch
    expect(refetchBootstrap).not.toHaveBeenCalled()
    expect(setIsActionSheetOpen).toHaveBeenCalledWith(false)
  })

  it('counts API calls across macrotask', async () => {
    // Simulate async scheduling past a macrotask to ensure no zero-delay duplication
    let resolveMutate: () => void
    const mutate = vi.fn().mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          setTimeout(() => {
            resolveMutate = resolve
          }, 0)
        })
    )
    const snoozeMutation = { mutate, isPending: false }

    const state = {
      suppressPendingAutoOpenRef: { current: false },
      selectedThread: { id: 5 },
      setSelectedThread: vi.fn(),
      setIsActionSheetOpen: vi.fn(),
      setIsSetCurrentIssueOpen: vi.fn(),
      setIsShuffleOpen: vi.fn(),
      setErrorMessage: vi.fn(),
      setCurrentDie: vi.fn(),
      setThreadToMigrate: vi.fn(),
      setShowMigrationDialog: vi.fn(),
      setIsRolling: vi.fn(),
      setDiceState: vi.fn(),
      rollIntervalRef: { current: null },
      rollTimeoutRef: { current: null },
      staleThread: null,
    }

    const mutations = {
      setDieMutation: { mutate: vi.fn(), isPending: false },
      clearManualDieMutation: { mutate: vi.fn(), isPending: false },
      rollMutation: { mutate: vi.fn(), isPending: false },
      snoozeMutation,
      unsnoozeMutation: { mutate: vi.fn(), isPending: false },
      skipMutation: { mutate: vi.fn(), isPending: false },
      unskipMutation: { mutate: vi.fn(), isPending: false },
      moveToFrontMutation: { mutate: vi.fn(), isPending: false },
      moveToBackMutation: { mutate: vi.fn(), isPending: false },
      shuffleQueueMutation: { mutate: vi.fn(), isPending: false },
    }

    const refetchBootstrap = vi.fn().mockResolvedValue({})

    const { result } = renderHook(() =>
      useRollActions({
        state: state as any,
        bootstrap: { pending_thread_id: 5, snoozed_threads: [] } as any,
        rollPool: [],
        navigate: vi.fn(),
        mutations,
        refetchBootstrap,
        enterRatingView: vi.fn(),
        threadsApi: { setPending: vi.fn() } as any,
      })
    )

    let promise: Promise<void>
    act(() => {
      promise = result.current.handleAction('snooze')
    })

    // wait for macrotask
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0))
      resolveMutate!()
      await promise
    })

    expect(refetchBootstrap).not.toHaveBeenCalled()
  })
})
