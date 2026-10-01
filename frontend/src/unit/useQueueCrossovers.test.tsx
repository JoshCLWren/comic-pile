import { renderHook, waitFor } from '@testing-library/react'
import type { PropsWithChildren } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { CrossoverGroupsApi } from '../hooks/useCrossoverGroups'
import { useQueueCrossovers } from '../pages/QueuePage/useQueueCrossovers'
import type { ThreadListItem } from '../types'

const listForThreads = vi.fn<CrossoverGroupsApi['listForThreads']>()

const api: CrossoverGroupsApi = { listForThreads }

function createWrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return function Wrapper({ children }: PropsWithChildren) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

function thread(id: number): ThreadListItem {
  return {
    id,
    title: `Series ${id}`,
    format: 'Comic',
    status: 'active',
    queue_position: id,
    issues_remaining: 3,
  } as ThreadListItem
}

function renderCrossovers(threads: ThreadListItem[]) {
  return renderHook(() => useQueueCrossovers(threads, api), { wrapper: createWrapper() })
}

beforeEach(() => {
  listForThreads.mockReset()
})

describe('useQueueCrossovers', () => {
  it('never fetches when the queue is empty', () => {
    const { result } = renderCrossovers([])

    expect(result.current.groupsForThread(1)).toEqual([])
    expect(result.current.isPending).toBe(false)
    expect(result.current.hasError).toBe(false)
    expect(listForThreads).not.toHaveBeenCalled()
  })

  it('resolves memberships for every queued thread from one batched request', async () => {
    listForThreads.mockResolvedValue({
      7: [{ id: 11, name: 'Rotworld' }],
      12: [],
    })

    const { result } = renderCrossovers([thread(7), thread(12)])

    await waitFor(() =>
      expect(result.current.groupsForThread(7)).toEqual([{ id: 11, name: 'Rotworld' }]),
    )
    expect(result.current.groupsForThread(12)).toEqual([])
    expect(listForThreads).toHaveBeenCalledTimes(1)
    expect(listForThreads).toHaveBeenCalledWith([7, 12])
  })

  it('reports the shared failure without inventing memberships', async () => {
    listForThreads.mockRejectedValue(new Error('crossover batch unavailable'))

    const { result } = renderCrossovers([thread(7)])

    await waitFor(() => expect(result.current.hasError).toBe(true))
    expect(result.current.groupsForThread(7)).toEqual([])
  })
})