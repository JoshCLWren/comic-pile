import { renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useDependencyGroups } from '../hooks/useDependencyGroups'
import { dependencyGroupsApi } from '../services/api-dependency-groups'

vi.mock('../services/api-dependency-groups', () => ({
  dependencyGroupsApi: {
    listForThread: vi.fn(),
  },
}))

const mockedDependencyGroupsApi = vi.mocked(dependencyGroupsApi)

beforeEach(() => {
  vi.clearAllMocks()
})

describe('useDependencyGroups', () => {
  it('does not request groups without an active thread', () => {
    const { result } = renderHook(() => useDependencyGroups(null))

    expect(result.current).toEqual({ groups: [], isLoading: false, error: null })
    expect(mockedDependencyGroupsApi.listForThread).not.toHaveBeenCalled()
  })

  it('loads owned groups for the active thread', async () => {
    mockedDependencyGroupsApi.listForThread.mockResolvedValue([
      { id: 7, name: 'Annihilation' },
    ])

    const { result } = renderHook(() => useDependencyGroups(42))

    expect(result.current.isLoading).toBe(true)
    await waitFor(() => expect(result.current.groups).toEqual([{ id: 7, name: 'Annihilation' }]))
    expect(result.current.isLoading).toBe(false)
    expect(mockedDependencyGroupsApi.listForThread).toHaveBeenCalledWith(42)
  })

  it('clears stale group responses when the active thread changes', async () => {
    let resolveFirst: ((value: { id: number; name: string }[]) => void) | undefined
    mockedDependencyGroupsApi.listForThread
      .mockImplementationOnce(
        () => new Promise((resolve) => {
          resolveFirst = resolve
        }),
      )
      .mockResolvedValueOnce([{ id: 9, name: 'Infinity' }])

    const { result, rerender } = renderHook(
      ({ threadId }) => useDependencyGroups(threadId),
      { initialProps: { threadId: 42 } },
    )

    rerender({ threadId: 99 })
    await waitFor(() => expect(result.current.groups).toEqual([{ id: 9, name: 'Infinity' }]))

    resolveFirst?.([{ id: 7, name: 'Annihilation' }])
    await Promise.resolve()

    expect(result.current.groups).toEqual([{ id: 9, name: 'Infinity' }])
  })

  it('ignores stale errors while preserving the current Error instance', async () => {
    let rejectFirst: ((reason: Error) => void) | undefined
    mockedDependencyGroupsApi.listForThread
      .mockImplementationOnce(
        () => new Promise((_, reject) => {
          rejectFirst = reject
        }),
      )
      .mockRejectedValueOnce(new Error('current request failed'))

    const { result, rerender } = renderHook(
      ({ threadId }) => useDependencyGroups(threadId),
      { initialProps: { threadId: 42 } },
    )

    rerender({ threadId: 99 })
    await waitFor(() => expect(result.current.error?.message).toBe('current request failed'))

    rejectFirst?.(new Error('stale request failed'))
    await Promise.resolve()

    expect(result.current.error?.message).toBe('current request failed')
    expect(result.current.groups).toEqual([])
    expect(result.current.isLoading).toBe(false)
  })

  it('returns a normalized error when loading fails', async () => {
    mockedDependencyGroupsApi.listForThread.mockRejectedValue('offline')

    const { result } = renderHook(() => useDependencyGroups(42))

    await waitFor(() => expect(result.current.error?.message).toBe('Unable to load reading-order groups'))
    expect(result.current.groups).toEqual([])
    expect(result.current.isLoading).toBe(false)
  })
})
