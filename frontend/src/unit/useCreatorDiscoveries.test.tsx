import { renderHook, waitFor } from './testingLibrary'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useCreatorDiscoveries } from '../hooks/useCreatorDiscoveries'
import { creatorDiscoveryApi } from '../services/creatorDiscoveryApi'
import type { CreatorDiscoveryResponse } from '../types/index'

const original_creatorDiscoveryApi = { ...creatorDiscoveryApi }
const mock_creatorDiscoveryApi = { getDiscoveries: vi.fn() }

const mockedGetDiscoveries = (mock_creatorDiscoveryApi.getDiscoveries as any)

function makeResponse(): CreatorDiscoveryResponse {
  return {
    views: [
      {
        mode: 'consistently_loved',
        title: 'Most consistently loved',
        description: 'High personal average on a meaningful sample.',
        min_sample: 3,
        total: 0,
        truncated: false,
        max_entries: 10,
        entries: [],
      },
    ],
    coverage: {
      rated_issues_total: 0,
      rated_issues_with_creator_metadata: 0,
      ratings_complete: true,
    },
    minimum_reliable_sample: 3,
    max_entries_per_view: 10,
  }
}

function createWrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

beforeEach(() => {
  Object.assign(creatorDiscoveryApi, mock_creatorDiscoveryApi)
  vi.clearAllMocks()
  mockedGetDiscoveries.mockResolvedValue(makeResponse())
})

afterEach(() => {
  Object.assign(creatorDiscoveryApi, original_creatorDiscoveryApi)
})


describe('useCreatorDiscoveries', () => {
  it('fetches through the canonical query key once enabled', async () => {
    const { result } = renderHook(() => useCreatorDiscoveries(), {
      wrapper: createWrapper(),
    })

    await waitFor(() => expect(result.current.isPending).toBe(false))
    expect(mockedGetDiscoveries).toHaveBeenCalledTimes(1)
    expect(result.current.data?.minimum_reliable_sample).toBe(3)
    expect(result.current.isError).toBe(false)
  })

  it('stays disabled when the exploration mode is not visible', () => {
    const { result } = renderHook(() => useCreatorDiscoveries(false), {
      wrapper: createWrapper(),
    })

    expect(result.current.isPending).toBe(true)
    expect(mockedGetDiscoveries).not.toHaveBeenCalled()
  })

  it('surfaces a failed load for the caller to explain', async () => {
    mockedGetDiscoveries.mockRejectedValue(new Error('boom'))
    const { result } = renderHook(() => useCreatorDiscoveries(), {
      wrapper: createWrapper(),
    })

    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(result.current.data).toBeUndefined()
  })
})
