import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const axiosInstance = vi.hoisted(() => ({
  post: vi.fn(),
  get: vi.fn(),
  interceptors: {
    request: { use: vi.fn() },
    response: { use: vi.fn() },
  },
}))

vi.mock('axios', () => ({
  default: {
    create: vi.fn(() => axiosInstance),
  },
}))

import { useRollDependencies } from '../pages/RollPage/useRollDependencies'
import { useRollPageState } from '../pages/RollPage/useRollPageState'
import type { RollBootstrapResponse } from '../types/rollBootstrap'

function bootstrapWith(
  blockedThreads: RollBootstrapResponse['blocked_threads'],
): RollBootstrapResponse {
  return {
    session_id: 1,
    user_id: 1,
    current_die: 20,
    manual_die: null,
    pending_thread_id: null,
    last_rolled_result: null,
    session_mode: {
      active_bandwidth: null,
      predicted_bandwidth: null,
      bandwidth_confidence: null,
      bandwidth_source: null,
      bandwidth_version: null,
      active_intent: null,
      predicted_intent: null,
      intent_confidence: null,
      intent_source: null,
      intent_version: null,
      session_mode_correction_guidance: null,
    },
    active_thread: null,
    roll_pool: [],
    snoozed_threads: [],
    snoozed_count: 0,
    skipped_thread_ids: [],
    skipped_threads: [],
    blocked_count: blockedThreads.length,
    blocked_threads: blockedThreads,
    stale_thread_count: 0,
    stale_thread: null,
  }
}

describe('useRollDependencies batched blocking details', () => {
  beforeEach(() => {
    axiosInstance.post.mockReset()
  })

  function renderDependencies(bootstrap: RollBootstrapResponse | null) {
    return renderHook(() => {
      const state = useRollPageState()
      const dependencies = useRollDependencies({ state, bootstrap })
      return { state, handleToggleBlocked: dependencies.handleToggleBlocked }
    })
  }

  it('loads one named-blocker map for every blocked thread in a single request', async () => {
    axiosInstance.post.mockResolvedValue({
      threads: {
        '2': {
          blocking_reasons: [],
          blocking_dependencies: [
            { thread_id: 9, thread_title: 'Prequel', issue_number: '1', label: 'Read Prequel first' },
          ],
        },
      },
    })
    const { result } = renderDependencies(
      bootstrapWith([{ id: 2, title: 'Blocked', format: 'Comic' }]),
    )

    await act(async () => {
      await result.current.handleToggleBlocked()
    })

    expect(axiosInstance.post).toHaveBeenCalledTimes(1)
    expect(axiosInstance.post).toHaveBeenCalledWith('/v1/threads:getBlockingInfo', {
      thread_ids: [2],
    })
    expect(result.current.state.blockingDependencyMap).toEqual({
      2: [{ thread_id: 9, thread_title: 'Prequel', issue_number: '1', label: 'Read Prequel first' }],
    })
    expect(result.current.state.blockedExpanded).toBe(true)
  })

  it('falls back to empty blocker lists without a bootstrap or dependency payload', async () => {
    axiosInstance.post.mockResolvedValue({ threads: { '3': { blocking_reasons: ['legacy'] } } })
    const { result } = renderDependencies(null)

    await act(async () => {
      await result.current.handleToggleBlocked()
    })

    expect(axiosInstance.post).toHaveBeenCalledWith('/v1/threads:getBlockingInfo', {
      thread_ids: [],
    })
    expect(result.current.state.blockingDependencyMap).toEqual({ 3: [] })
    expect(result.current.state.blockedExpanded).toBe(true)
  })

  it('clears the blocker map and still expands when the batch request fails', async () => {
    axiosInstance.post.mockRejectedValue(new Error('blocking batch unavailable'))
    const { result } = renderDependencies(
      bootstrapWith([{ id: 4, title: 'Blocked', format: 'Comic' }]),
    )

    await act(async () => {
      await result.current.handleToggleBlocked()
    })

    expect(result.current.state.blockingDependencyMap).toEqual({})
    expect(result.current.state.blockedExpanded).toBe(true)

    await act(async () => {
      await result.current.handleToggleBlocked()
    })
    expect(axiosInstance.post).toHaveBeenCalledTimes(1)
    expect(result.current.state.blockedExpanded).toBe(false)
  })
})
