import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useContinuityReadiness } from '../hooks/useContinuityReadiness'

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
    rerender({ issueId: 8 })
    await waitFor(() => expect(result.current.readiness?.node_id).toBe(8))

    act(() => resolveFirst({
      node_type: 'issue', node_id: 7, is_readable: false, evaluated_issue_id: 7, blockers: [],
    }))
    expect(result.current.readiness?.node_id).toBe(8)
  })
})
