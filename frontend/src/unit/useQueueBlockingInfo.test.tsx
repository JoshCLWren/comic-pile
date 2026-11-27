import { renderHook, waitFor } from '@testing-library/react'
import type { PropsWithChildren } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useThreadBlockingInfo } from '../hooks/useDependencies'
import { useQueueBlockingInfo } from '../hooks/useQueueBlockingInfo'
import type { QueueBlockingInfoApi } from '../hooks/useQueueBlockingInfo'
import type { BatchEligibilityResponse } from '../types'

const explainEligibility = vi.fn<QueueBlockingInfoApi['explainEligibility']>()

const api: QueueBlockingInfoApi = { explainEligibility }

function createWrapper(client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })) {
  return function Wrapper({ children }: PropsWithChildren) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

describe('useQueueBlockingInfo', () => {
  beforeEach(() => {
    explainEligibility.mockReset()
  })

  it('returns an empty map without fetching when the queue has no threads', () => {
    const { result } = renderHook(() => useQueueBlockingInfo([], api), { wrapper: createWrapper() })
    expect(result.current).toEqual({})
    expect(explainEligibility).not.toHaveBeenCalled()
  })

  it('batch-loads named blockers keyed by numeric thread id', async () => {
    const response: BatchEligibilityResponse = {
      threads: {
        '12': { thread_id: 12, eligible: false, is_blocked: true, next_issue_id: null, blocking_reasons: ['Blocked'], blocking_dependencies: [] },
        '7': {
          thread_id: 7,
          eligible: false,
          is_blocked: true,
          next_issue_id: 70,
          blocking_reasons: ['Read Prequel first'],
          blocking_dependencies: [
            { thread_id: 3, thread_title: 'Prequel', issue_number: '2', label: 'Read Prequel first' },
          ],
        },
      },
    }
    explainEligibility.mockResolvedValue(response)
    const { result } = renderHook(() => useQueueBlockingInfo([12, 7], api), { wrapper: createWrapper() })

    await waitFor(() =>
      expect(result.current[7]).toEqual([
        { thread_id: 3, thread_title: 'Prequel', issue_number: '2', label: 'Read Prequel first' },
      ]),
    )
    expect(result.current[12]).toEqual([])
    expect(explainEligibility).toHaveBeenCalledTimes(1)
    expect(explainEligibility).toHaveBeenCalledWith([7, 12])
  })

  it('degrades to an empty map when the batch request fails', async () => {
    explainEligibility.mockRejectedValue(new Error('blocking batch unavailable'))
    const { result } = renderHook(() => useQueueBlockingInfo([5], api), { wrapper: createWrapper() })
    await waitFor(() => expect(result.current).toEqual({}))
    expect(explainEligibility).toHaveBeenCalledTimes(1)
  })
})


it('shares the raw batch response when navigating from Queue to thread details', async () => {
  const response: BatchEligibilityResponse = {
    threads: { 7: { thread_id: 7, eligible: true, is_blocked: false, next_issue_id: 70, blocking_reasons: [], blocking_dependencies: [] } },
  }
  explainEligibility.mockResolvedValue(response)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 30_000 } } })
  const wrapper = createWrapper(client)
  const queue = renderHook(() => useQueueBlockingInfo([7], api), { wrapper })
  await waitFor(() => expect(queue.result.current[7]).toEqual([]))
  queue.unmount()
  const detail = renderHook(() => useThreadBlockingInfo(7), { wrapper })
  expect(detail.result.current.data).toEqual(response)
  expect(detail.result.current.data?.threads[7]?.is_blocked).toBe(false)
  expect(explainEligibility).toHaveBeenCalledTimes(1)
})
