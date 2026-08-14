import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useContinuityChains } from '../hooks/useContinuityChains'

const mocks = vi.hoisted(() => ({ resolveChains: vi.fn() }))

vi.mock('../services/api-continuity-readiness', () => ({
  continuityReadinessApi: { resolveChains: mocks.resolveChains },
}))

const chains = {
  node_type: 'issue' as const,
  node_id: 7,
  evaluated_issue_id: null,
  direct_blockers: [],
  chains: [],
  readable_prerequisites: [],
  diagnostics: [],
}

beforeEach(() => {
  mocks.resolveChains.mockReset()
})

describe('useContinuityChains', () => {
  it('stays idle when there is no issue identity', () => {
    const { result } = renderHook(() => useContinuityChains(null))

    expect(result.current).toMatchObject({
      chains: null,
      isLoading: false,
      error: null,
    })
    expect(mocks.resolveChains).not.toHaveBeenCalled()
  })

  it('loads chains and refetches on demand', async () => {
    mocks.resolveChains.mockResolvedValue(chains)
    const { result } = renderHook(() => useContinuityChains(7))

    expect(result.current.isLoading).toBe(true)
    await waitFor(() => expect(result.current.chains).toEqual(chains))

    act(() => result.current.refetch())
    await waitFor(() => expect(mocks.resolveChains).toHaveBeenCalledTimes(2))
  })

  it.each([
    [new Error('offline'), 'offline'],
    ['offline', 'Unable to load chain'],
  ])('normalizes a failed chain request', async (reason, message) => {
    mocks.resolveChains.mockRejectedValue(reason)
    const { result } = renderHook(() => useContinuityChains(7))

    await waitFor(() => expect(result.current.error?.message).toBe(message))
    expect(result.current.isLoading).toBe(false)
  })

  it('ignores a response after the active issue changes', async () => {
    let resolveRequest: ((value: typeof chains) => void) | undefined
    mocks.resolveChains.mockReturnValue(
      new Promise<typeof chains>((resolve) => {
        resolveRequest = resolve
      }),
    )
    const { result, rerender } = renderHook(
      ({ issueId }) => useContinuityChains(issueId),
      { initialProps: { issueId: 7 as number | null } },
    )

    rerender({ issueId: null })
    await act(async () => resolveRequest?.(chains))

    expect(result.current.chains).toBeNull()
    expect(result.current.isLoading).toBe(false)
  })

  it('ignores a rejection after unmount', async () => {
    let rejectRequest: ((reason: Error) => void) | undefined
    mocks.resolveChains.mockReturnValue(
      new Promise((_resolve, reject) => {
        rejectRequest = reject
      }),
    )
    const { unmount } = renderHook(() => useContinuityChains(7))

    unmount()
    await act(async () => rejectRequest?.(new Error('late')))
  })
})
