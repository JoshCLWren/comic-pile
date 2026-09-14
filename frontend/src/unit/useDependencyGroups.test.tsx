import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { type ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useDependencyGroups, type DependencyGroupsApi } from '../hooks/useDependencyGroups'

// Injectable fake passed through the real hook arg — no module mocking of the API.
const listForThread = vi.fn<DependencyGroupsApi['listForThread']>()
const groupsApi: DependencyGroupsApi = { listForThread }

function createTestWrapper() {
  const client = new QueryClient()
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
  return { client, wrapper }
}

beforeEach(() => {
  listForThread.mockReset()
})

describe('useDependencyGroups', () => {
  it('does not request groups without an active thread', () => {
    const { wrapper } = createTestWrapper()
    const { result } = renderHook(() => useDependencyGroups(null, groupsApi), { wrapper })

    expect(result.current).toEqual({ groups: [], isLoading: false, error: null })
    expect(listForThread).not.toHaveBeenCalled()
  })

  it('loads owned groups for the active thread', async () => {
    listForThread.mockResolvedValue([
      { id: 7, name: 'Annihilation' },
    ])

    const { wrapper } = createTestWrapper()
    const { result } = renderHook(() => useDependencyGroups(42, groupsApi), { wrapper })

    expect(result.current.isLoading).toBe(true)
    await waitFor(() => expect(result.current.groups).toEqual([{ id: 7, name: 'Annihilation' }]))
    expect(result.current.isLoading).toBe(false)
    expect(listForThread).toHaveBeenCalledWith(42)
  })

  it('clears stale group responses when the active thread changes', async () => {
    let resolveFirst: ((value: { id: number; name: string }[]) => void) | undefined
    listForThread
      .mockImplementationOnce(
        () => new Promise((resolve) => {
          resolveFirst = resolve
        }),
      )
      .mockResolvedValueOnce([{ id: 9, name: 'Infinity' }])

    const { wrapper } = createTestWrapper()
    const { result, rerender } = renderHook(
      ({ threadId }) => useDependencyGroups(threadId, groupsApi),
      { wrapper,
        initialProps: { threadId: 42 } },
    )

    rerender({ threadId: 99 })
    await waitFor(() => expect(result.current.groups).toEqual([{ id: 9, name: 'Infinity' }]))

    resolveFirst?.([{ id: 7, name: 'Annihilation' }])
    await Promise.resolve()

    expect(result.current.groups).toEqual([{ id: 9, name: 'Infinity' }])
  })

  it('ignores stale errors while preserving the current Error instance', async () => {
    let rejectFirst: ((reason: Error) => void) | undefined
    listForThread
      .mockImplementationOnce(
        () => new Promise((_, reject) => {
          rejectFirst = reject
        }),
      )
      .mockRejectedValueOnce(new Error('current request failed'))

    const { wrapper } = createTestWrapper()
    const { result, rerender } = renderHook(
      ({ threadId }) => useDependencyGroups(threadId, groupsApi),
      { wrapper,
        initialProps: { threadId: 42 } },
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
    listForThread.mockRejectedValue('offline')

    const { wrapper } = createTestWrapper()
    const { result } = renderHook(() => useDependencyGroups(42, groupsApi), { wrapper })

    await waitFor(() => expect(result.current.error?.message).toBe('Unable to load reading-order groups'))
    expect(result.current.groups).toEqual([])
    expect(result.current.isLoading).toBe(false)
  })
})