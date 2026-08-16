import { act, renderHook, waitFor } from '@testing-library/react'
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
    const { result } = renderHook(() => useQueueThreads())

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
