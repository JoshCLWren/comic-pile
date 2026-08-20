import { act, renderHook, waitFor } from '@testing-library/react'
import type { PropsWithChildren } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useQueueThreads } from '../hooks/useQueue'
import * as useThreadModule from '../hooks/useThread'
import { threadsApi } from '../services/api'
import type { Thread } from '../types'

vi.mock('../services/api', () => ({
  threadsApi: {
    list: vi.fn(),
  },
}))

const mockedThreadsApi = vi.mocked(threadsApi)

function createWrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return function Wrapper({ children }: PropsWithChildren) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  mockedThreadsApi.list.mockResolvedValue({
    threads: Array.from({ length: 51 }, (_, index) => ({ id: index + 1 }) as Thread),
    next_page_token: 'page-2',
  })
})

describe('bounded thread hydration guard', () => {
  it('does not export the universal useThreads hook anymore', () => {
    expect('useThreads' in useThreadModule).toBe(false)
  })

  it('fetches a single bounded page and never auto-traverses pages', async () => {
    const wrapper = createWrapper()
    const { result } = renderHook(() => useQueueThreads(), { wrapper })

    await waitFor(() => expect(result.current.isPending).toBe(false))

    expect(mockedThreadsApi.list).toHaveBeenCalledTimes(1)
    expect(mockedThreadsApi.list).toHaveBeenCalledWith(
      expect.objectContaining({ page_size: 50 }),
      undefined,
    )
    expect(result.current.data).toHaveLength(51)
    expect(result.current.nextPageToken).toBe('page-2')

    await act(async () => {
      await Promise.resolve()
    })

    expect(mockedThreadsApi.list).toHaveBeenCalledTimes(1)
  })
})
