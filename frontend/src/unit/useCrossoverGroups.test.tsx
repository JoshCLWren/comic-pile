import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const { listForThreads } = vi.hoisted(() => ({
  listForThreads: vi.fn(),
}))

vi.mock('../services/api-dependency-groups', () => ({
  dependencyGroupsApi: { listForThreads },
}))

import { useCrossoverGroups } from '../hooks/useCrossoverGroups'

describe('useCrossoverGroups', () => {
  beforeEach(() => {
    listForThreads.mockReset()
  })

  it('returns an immediate empty state when no thread ids are requested', async () => {
    const { result } = renderHook(() => useCrossoverGroups([]))

    await waitFor(() => expect(result.current.isPending).toBe(false))
    expect(result.current.groupsByThreadId).toEqual({})
    expect(result.current.error).toBeNull()
    expect(listForThreads).not.toHaveBeenCalled()
  })

  it('deduplicates and sorts ids while filling missing groups with empty arrays', async () => {
    listForThreads.mockResolvedValueOnce({
      2: [{ id: 7, name: 'Cosmic', membership_count: 1 }],
    })

    const { result } = renderHook(() => useCrossoverGroups([3, 2, 3]))

    await waitFor(() => expect(result.current.isPending).toBe(false))
    expect(listForThreads).toHaveBeenCalledWith([2, 3])
    expect(result.current.groupsByThreadId[2]).toHaveLength(1)
    expect(result.current.groupsByThreadId[3]).toEqual([])
  })

  it('coalesces simultaneous hooks into one request', async () => {
    listForThreads.mockResolvedValueOnce({ 1: [], 2: [] })

    const first = renderHook(() => useCrossoverGroups([1]))
    const second = renderHook(() => useCrossoverGroups([2]))

    await waitFor(() => expect(first.result.current.isPending).toBe(false))
    await waitFor(() => expect(second.result.current.isPending).toBe(false))
    expect(listForThreads).toHaveBeenCalledTimes(1)
    expect(listForThreads).toHaveBeenCalledWith([1, 2])
  })

  it('chunks requests larger than the backend limit', async () => {
    listForThreads.mockResolvedValue({})
    const ids = Array.from({ length: 201 }, (_, index) => index + 1)

    const { result } = renderHook(() => useCrossoverGroups(ids))

    await waitFor(() => expect(result.current.isPending).toBe(false))
    expect(listForThreads).toHaveBeenCalledTimes(2)
    expect(listForThreads.mock.calls[0][0]).toHaveLength(200)
    expect(listForThreads.mock.calls[1][0]).toEqual([201])
  })

  it('normalizes non-Error failures', async () => {
    listForThreads.mockRejectedValueOnce('offline')

    const { result } = renderHook(() => useCrossoverGroups([9]))

    await waitFor(() => expect(result.current.isPending).toBe(false))
    expect(result.current.error).toEqual(new Error('Failed to load crossovers'))
    expect(result.current.groupsByThreadId).toEqual({})
  })

  it('preserves Error failures', async () => {
    const failure = new Error('boom')
    listForThreads.mockRejectedValueOnce(failure)

    const { result } = renderHook(() => useCrossoverGroups([9]))

    await waitFor(() => expect(result.current.isPending).toBe(false))
    expect(result.current.error).toBe(failure)
  })

  it('ignores a successful response after the request is replaced', async () => {
    let resolveFirst!: (value: Record<number, never[]>) => void
    listForThreads
      .mockImplementationOnce(() => new Promise((resolve) => { resolveFirst = resolve }))
      .mockResolvedValueOnce({ 2: [] })

    const { result, rerender } = renderHook(
      ({ ids }) => useCrossoverGroups(ids),
      { initialProps: { ids: [1] } },
    )

    await waitFor(() => expect(listForThreads).toHaveBeenCalledTimes(1))
    rerender({ ids: [2] })
    await waitFor(() => expect(listForThreads).toHaveBeenCalledTimes(2))
    await waitFor(() => expect(result.current.isPending).toBe(false))

    await act(async () => {
      resolveFirst({ 1: [] })
      await Promise.resolve()
    })

    expect(result.current.groupsByThreadId).toEqual({ 2: [] })
  })
})
