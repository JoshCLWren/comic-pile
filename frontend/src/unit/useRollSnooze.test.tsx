import { renderHook, act } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { useRollSnooze } from '../pages/RollPage/useRollSnooze'
import { useRollPageState } from '../pages/RollPage/useRollPageState'
import type { SnoozeMutationOutcome } from '../hooks/useSnooze'
import type { RatingThread } from '../pages/RollPage/types'
import type { RollResponse } from '../types'

function ratingThread(id: number): RatingThread {
  return {
    id,
    title: `Series ${id}`,
    format: 'Comic',
    issues_remaining: 3,
    queue_position: 1,
    total_issues: 6,
    reading_progress: null,
    issue_id: null,
    issue_number: null,
    next_issue_id: null,
    next_issue_number: null,
    last_rolled_result: null,
  }
}

function nextOffer(): RollResponse {
  return {
    thread_id: 9,
    title: 'Next Series',
    format: 'Comic',
    issues_remaining: 2,
    queue_position: 2,
    die_size: 8,
    result: 1,
    offset: 0,
    snoozed_count: 1,
    issue_id: null,
    issue_number: null,
    next_issue_id: null,
    next_issue_number: null,
    total_issues: 6,
    reading_progress: null,
  }
}

function committedOutcome(): SnoozeMutationOutcome {
  return {
    response: {
      current_die: 12,
      pending_thread_id: null,
      reading_mode_suggested: false,
      correction: null,
    },
    refreshed: true,
    refreshError: null,
  }
}

function renderRollSnooze(
  mutate: (expectedPendingThreadId?: number) => Promise<SnoozeMutationOutcome>,
  options: { threadId?: number; onRefreshFailed?: (refreshError: unknown) => void } = {},
) {
  const { threadId = 7, onRefreshFailed } = options
  const refetchBootstrap = vi.fn().mockResolvedValue(undefined)

  const { result } = renderHook(() => {
    const state = useRollPageState()

    const snooze = useRollSnooze({
      state,
      snoozeMutation: { mutate },
      unsnoozeMutation: { mutate: vi.fn().mockResolvedValue(undefined) },
      refetchBootstrap,
      onRefreshFailed,
    })

    return { state, snooze }
  })

  act(() => {
    result.current.state.setActiveRatingThread(ratingThread(threadId))
    result.current.state.setIsRatingView(true)
    result.current.state.setIsRolling(true)
  })

  return { result, refetchBootstrap }
}

describe('useRollSnooze', () => {
  it('does not refetch bootstrap after a successful snooze', async () => {
    const mutate = vi.fn().mockResolvedValue(committedOutcome())
    const { result, refetchBootstrap } = renderRollSnooze(mutate)

    await act(async () => {
      await result.current.snooze.handleSnooze()
    })

    expect(mutate).toHaveBeenCalledWith(7)
    // The successful mutation owns the single authoritative refresh.
    expect(refetchBootstrap).not.toHaveBeenCalled()
    expect(result.current.state.isRolling).toBe(false)
    expect(result.current.state.isRatingView).toBe(false)
    expect(result.current.state.activeRatingThread).toBeNull()
  })

  it('clears the rating view only after the mutation resolves', async () => {
    let resolveMutate: (outcome: SnoozeMutationOutcome) => void = () => {}
    const mutate = vi.fn(
      () => new Promise<SnoozeMutationOutcome>((resolve) => {
        resolveMutate = resolve
      }),
    )
    const { result, refetchBootstrap } = renderRollSnooze(mutate, { threadId: 42 })

    let request: Promise<void> = Promise.resolve()
    act(() => {
      request = result.current.snooze.handleSnooze()
    })

    // Before the mutation resolves the reader still owns the rating view.
    expect(result.current.state.isRatingView).toBe(true)
    expect(result.current.state.isRolling).toBe(true)

    await act(async () => {
      resolveMutate(committedOutcome())
      await request
    })

    expect(result.current.state.isRatingView).toBe(false)
    expect(result.current.state.isRolling).toBe(false)
    expect(refetchBootstrap).not.toHaveBeenCalled()
  })

  it('reports an exhausted authoritative refresh instead of closing silently', async () => {
    const refreshFailure = new Error('bootstrap unavailable')
    const mutate = vi.fn().mockResolvedValue({
      response: {
        current_die: 12,
        pending_thread_id: null,
        reading_mode_suggested: false,
        correction: null,
      },
      refreshed: false,
      refreshError: refreshFailure,
    } satisfies SnoozeMutationOutcome)
    const onRefreshFailed = vi.fn()
    const { result } = renderRollSnooze(mutate, { onRefreshFailed })

    await act(async () => {
      await result.current.snooze.handleSnooze()
    })

    // The snooze committed, so the rating view closes...
    expect(result.current.state.isRatingView).toBe(false)
    // ...but the stale pool/pending state is never silent.
    expect(onRefreshFailed).toHaveBeenCalledWith(refreshFailure)
  })

  it('exposes the refresh-only retry without repeating the snooze', async () => {
    const retryRefresh = vi.fn().mockResolvedValue(true)
    const mutate = vi.fn().mockResolvedValue(committedOutcome())
    const { result } = renderHook(() => useRollSnooze({
      state: useRollPageState(),
      snoozeMutation: { mutate, retryRefresh },
      unsnoozeMutation: { mutate: vi.fn().mockResolvedValue(undefined) },
      refetchBootstrap: vi.fn().mockResolvedValue(undefined),
    }))

    await act(async () => {
      await result.current.retryRefresh?.()
    })

    expect(retryRefresh).toHaveBeenCalledTimes(1)
    expect(mutate).not.toHaveBeenCalled()
  })

  it('rerolls through the Rust offer and refreshes the next offer', async () => {
    const reroll = vi.fn().mockResolvedValue(nextOffer())
    const refetchBootstrap = vi.fn().mockResolvedValue(undefined)
    const { result } = renderHook(() => {
      const state = useRollPageState()
      const snooze = useRollSnooze({
        state,
        snoozeMutation: { mutate: vi.fn() },
        rerollMutation: { mutate: reroll },
        unsnoozeMutation: { mutate: vi.fn().mockResolvedValue(undefined) },
        refetchBootstrap,
      })
      return { state, snooze }
    })

    act(() => {
      result.current.state.setActiveRatingThread(ratingThread(7))
      result.current.state.setIsRatingView(true)
      result.current.state.setIsRolling(true)
    })

    await act(async () => {
      await result.current.snooze.handleReroll()
    })

    expect(reroll).toHaveBeenCalledTimes(1)
    expect(refetchBootstrap).toHaveBeenCalledTimes(1)
    expect(result.current.state.isRatingView).toBe(false)
    expect(result.current.state.activeRatingThread).toBeNull()
  })

  it('enters the next offer from the response instead of refetching', async () => {
    const response = nextOffer()
    const reroll = vi.fn().mockResolvedValue(response)
    const enterRatingView = vi.fn().mockResolvedValue(undefined)
    const refetchBootstrap = vi.fn()
    const { result } = renderHook(() => {
      const state = useRollPageState()
      const snooze = useRollSnooze({
        state,
        snoozeMutation: { mutate: vi.fn() },
        rerollMutation: { mutate: reroll },
        enterRatingView,
        unsnoozeMutation: { mutate: vi.fn().mockResolvedValue(undefined) },
        refetchBootstrap,
      })
      return { state, snooze }
    })

    act(() => {
      result.current.state.setActiveRatingThread(ratingThread(7))
      result.current.state.setIsRatingView(true)
    })

    await act(async () => {
      await result.current.snooze.handleReroll()
    })

    expect(reroll).toHaveBeenCalledTimes(1)
    expect(enterRatingView).toHaveBeenCalledWith(
      response.thread_id,
      response.result,
      response,
    )
    expect(refetchBootstrap).not.toHaveBeenCalled()
  })
})
