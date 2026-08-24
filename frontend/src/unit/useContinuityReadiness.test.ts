import { act, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useContinuityReadiness } from '../hooks/useContinuityReadiness'
import { renderHookWithClient as renderHook } from './queryTestWrapper'

const mocks = vi.hoisted(() => ({ evaluate: vi.fn() }))

vi.mock('../services/api-continuity-readiness', () => ({
  continuityReadinessApi: { evaluate: mocks.evaluate },
}))

beforeEach(() => {
  mocks.evaluate.mockReset()
})

describe('useContinuityReadiness', () => {
  it('loads readiness and retries the same issue', async () => {
    const readiness = {
      node_type: 'issue',
      node_id: 7,
      is_readable: true,
      evaluated_issue_id: 7,
      blockers: [],
    }
    mocks.evaluate.mockResolvedValue(readiness)
    const { result } = renderHook(() => useContinuityReadiness(7))

    await waitFor(() => expect(result.current.readiness).toEqual(readiness))
    act(() => result.current.refetch())
    await waitFor(() => expect(mocks.evaluate).toHaveBeenCalledTimes(2))
  })

  it('ignores a late response after the issue changes', async () => {
    let resolveFirst: (value: unknown) => void = () => undefined
    mocks.evaluate
      .mockImplementationOnce(() => new Promise((resolve) => { resolveFirst = resolve }))
      .mockResolvedValueOnce({
        node_type: 'issue', node_id: 8, is_readable: true, evaluated_issue_id: 8, blockers: [],
      })

    const { result, rerender } = renderHook(({ issueId }) => useContinuityReadiness(issueId), {
      initialProps: { issueId: 7 as number | null },
    })
    
    // Initial query is pending (slow), rerender to issueId 8
    rerender({ issueId: 8 })
    // Wait for the new query (issueId 8) to complete
    await waitFor(() => expect(result.current.isLoading).toBe(false))
    await waitFor(() => expect(result.current.readiness?.node_id).toBe(8))

    // Now resolve the first (stale) query - it should be ignored
    act(() => resolveFirst({
      node_type: 'issue', node_id: 7, is_readable: false, evaluated_issue_id: 7, blockers: [],
    }))
    expect(result.current.readiness?.node_id).toBe(8)
  })
})
