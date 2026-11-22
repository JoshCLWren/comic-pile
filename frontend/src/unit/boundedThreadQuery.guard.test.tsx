import { act, renderHook, waitFor } from '@testing-library/react'
import type { PropsWithChildren } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useQueueThreads } from '../hooks/useQueue'
import * as useThreadModule from '../hooks/useThread'
import { threadsApi } from '../services/api-threads'
import type { ThreadListItem } from '../types'

const original_threadsApi = { ...threadsApi }
const mock_threadsApi = { list: vi.fn() }

// SAFETY: test mock narrows the API object for typed mock access.
const mockedThreadsApi = (mock_threadsApi as any)

function createWrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return function Wrapper({ children }: PropsWithChildren) {
    return (
      <QueryClientProvider client={client}>
        <MemoryRouter>{children}</MemoryRouter>
      </QueryClientProvider>
    )
  }
}

beforeEach(() => {
  Object.assign(threadsApi, mock_threadsApi)
  vi.clearAllMocks()
  // SAFETY: Test data supplies only id; remaining ThreadListItem fields are never read by this guard test.
  mockedThreadsApi.list.mockResolvedValue({
    threads: Array.from({ length: 51 }, (_, index) => ({ id: index + 1 }) as ThreadListItem),
    next_page_token: 'page-2',
    active_count: 51,
  })
})

afterEach(() => {
  Object.assign(threadsApi, original_threadsApi)
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
