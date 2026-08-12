import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useContinuityReadiness } from '../hooks/useContinuityReadiness'

const mocks = vi.hoisted(() => ({ evaluate: vi.fn() }))

vi.mock('../services/api-continuity-readiness', () => ({
  continuityReadinessApi: { evaluate: mocks.evaluate },
}))

const readiness = {
  node_type: 'issue' as const,
  node_id: 7,
  is_readable: true,
  evaluated_issue_id: 7,
  blockers: [],
}

beforeEach(() => {
  mocks.evaluate.mockReset()
})

describe('useContinuityReadiness', () => {
  it('stays idle when there is no issue identity', () => {
    const { result } = renderHook(() => useContinuityReadiness(null))

    expect(result.current).toMatchObject({
      readiness: null,
      isLoading: false,
      error: null,
    })
    expect(mocks.evaluate).not.toHaveBeenCalled()
  })

  it('loads readiness and refetches it on demand', async () => {
    mocks.evaluate.mockResolvedValue(readiness)
    const { result } = renderHook(() => useContinuityReadiness(7))

    expect(result.current.isLoading).toBe(true)
    await waitFor(() => expect(result.current.readiness).toEqual(readiness))

    act(() => result.current.refetch())
    await waitFor(() => expect(mocks.evaluate).toHaveBeenCalledTimes(2))
  })

  it.each([
    [new Error('offline'), 'offline'],
    ['offline', 'Unable to load readiness'],
  ])('normalizes a failed readiness request', async (reason, message) => {
    mocks.evaluate.mockRejectedValue(reason)
    const { result } = renderHook(() => useContinuityReadiness(7))

    await waitFor(() => expect(result.current.error?.message).toBe(message))
    expect(result.current.isLoading).toBe(false)
  })

  it('ignores a response after the active issue changes', async () => {
    let resolveRequest: ((value: typeof readiness) => void) | undefined
    mocks.evaluate.mockReturnValue(
      new Promise<typeof readiness>((resolve) => {
        resolveRequest = resolve
      }),
    )
    const { result, rerender } = renderHook(
      ({ issueId }) => useContinuityReadiness(issueId),
      { initialProps: { issueId: 7 as number | null } },
    )

    rerender({ issueId: null })
    await act(async () => resolveRequest?.(readiness))

    expect(result.current.readiness).toBeNull()
    expect(result.current.isLoading).toBe(false)
  })

  it('ignores a rejection after unmount', async () => {
    let rejectRequest: ((reason: Error) => void) | undefined
    mocks.evaluate.mockReturnValue(
      new Promise((_resolve, reject) => {
        rejectRequest = reject
      }),
    )
    const { unmount } = renderHook(() => useContinuityReadiness(7))

    unmount()
    await act(async () => rejectRequest?.(new Error('late')))
  })
})
