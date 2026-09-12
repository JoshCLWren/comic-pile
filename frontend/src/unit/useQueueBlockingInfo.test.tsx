import { renderHook, waitFor } from '@testing-library/react'
import type { PropsWithChildren } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useQueueBlockingInfo } from '../hooks/useQueueBlockingInfo'
import type { QueueBlockingInfoApi } from '../hooks/useQueueBlockingInfo'
import type { BatchBlockingInfoResponse } from '../types'

const getBatchBlockingInfo = vi.fn<QueueBlockingInfoApi['getBatchBlockingInfo']>()

const api: QueueBlockingInfoApi = { getBatchBlockingInfo }

function createWrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return function Wrapper({ children }: PropsWithChildren) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

describe('useQueueBlockingInfo', () => {
  beforeEach(() => {
    getBatchBlockingInfo.mockReset()
  })

  it('returns an empty map without fetching when the queue has no threads', () => {
    const { result } = renderHook(() => useQueueBlockingInfo([], api), { wrapper: createWrapper() })
    expect(result.current).toEqual({})
    expect(getBatchBlockingInfo).not.toHaveBeenCalled()
  })

  it('batch-loads named blockers keyed by numeric thread id', async () => {
    const response: BatchBlockingInfoResponse = {
      threads: {
        '12': { blocking_reasons: ['Blocked'] },
        '7': {
          blocking_reasons: [],
          blocking_dependencies: [
            { thread_id: 3, thread_title: 'Prequel', issue_number: '2', label: 'Read Prequel first' },
          ],
        },
      },
    }
    getBatchBlockingInfo.mockResolvedValue(response)
    const { result } = renderHook(() => useQueueBlockingInfo([12, 7], api), { wrapper: createWrapper() })

    await waitFor(() =>
      expect(result.current[7]).toEqual([
        { thread_id: 3, thread_title: 'Prequel', issue_number: '2', label: 'Read Prequel first' },
      ]),
    )
    expect(result.current[12]).toEqual([])
    expect(getBatchBlockingInfo).toHaveBeenCalledTimes(1)
    expect(getBatchBlockingInfo).toHaveBeenCalledWith([7, 12])
  })

  it('degrades to an empty map when the batch request fails', async () => {
    getBatchBlockingInfo.mockRejectedValue(new Error('blocking batch unavailable'))
    const { result } = renderHook(() => useQueueBlockingInfo([5], api), { wrapper: createWrapper() })
    await waitFor(() => expect(result.current).toEqual({}))
    expect(getBatchBlockingInfo).toHaveBeenCalledTimes(1)
  })
})
