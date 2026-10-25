import { renderHook, act } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { useRollSnooze } from '../pages/RollPage/useRollSnooze'

describe('useRollSnooze', () => {
  it('does not refetch bootstrap after successful snooze', async () => {
    const setIsRolling = vi.fn()
    const setIsRatingView = vi.fn()
    const setRolledResult = vi.fn()
    const setSelectedThreadId = vi.fn()
    const setActiveRatingThread = vi.fn()
    const setErrorMessage = vi.fn()

    const state = {
      activeRatingThread: { id: 7 },
      setIsRolling,
      setIsRatingView,
      setRolledResult,
      setSelectedThreadId,
      setActiveRatingThread,
      setErrorMessage,
    } as any

    const mutate = vi.fn().mockResolvedValue({ correction: null })
    const snoozeMutation = { mutate }
    const unsnoozeMutation = { mutate: vi.fn() }
    const refetchBootstrap = vi.fn().mockResolvedValue({})

    const { result } = renderHook(() =>
      useRollSnooze({
        state,
        snoozeMutation,
        unsnoozeMutation,
        refetchBootstrap,
      })
    )

    await act(async () => {
      await result.current.handleSnooze()
    })

    expect(mutate).toHaveBeenCalledWith(7)
    // refetchBootstrap must not be called for snooze success
    expect(refetchBootstrap).not.toHaveBeenCalled()
    expect(setIsRolling).toHaveBeenCalledWith(false)
    expect(setIsRatingView).toHaveBeenCalledWith(false)
  })

  it('clears rating view only after mutation resolves', async () => {
    const setIsRolling = vi.fn()
    const setIsRatingView = vi.fn()
    const setRolledResult = vi.fn()
    const setSelectedThreadId = vi.fn()
    const setActiveRatingThread = vi.fn()
    const setErrorMessage = vi.fn()

    const state = {
      activeRatingThread: { id: 42 },
      setIsRolling,
      setIsRatingView,
      setRolledResult,
      setSelectedThreadId,
      setActiveRatingThread,
      setErrorMessage,
    } as any

    let resolveMutate: () => void
    const mutate = vi.fn().mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveMutate = () => resolve({ correction: null })
        })
    )
    const snoozeMutation = { mutate }
    const refetchBootstrap = vi.fn().mockResolvedValue({})

    const { result } = renderHook(() =>
      useRollSnooze({
        state,
        snoozeMutation,
        unsnoozeMutation: { mutate: vi.fn() },
        refetchBootstrap,
      })
    )

    let promise: Promise<void>
    act(() => {
      promise = result.current.handleSnooze()
    })

    // before mutation resolves, UI should not be cleared
    expect(setIsRolling).not.toHaveBeenCalled()

    await act(async () => {
      resolveMutate!()
      await promise
    })

    expect(setIsRolling).toHaveBeenCalledWith(false)
    expect(refetchBootstrap).not.toHaveBeenCalled()
  })
})
