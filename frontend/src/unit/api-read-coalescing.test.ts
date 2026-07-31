import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ThreadListResponse } from '../types'

const apiMocks = vi.hoisted(() => ({
  getAccessToken: vi.fn<() => string | null>(() => 'token-a'),
  listThreads: vi.fn(),
  listStaleThreads: vi.fn(),
  getCurrentSession: vi.fn(),
}))

vi.mock('../services/api', () => ({
  getAccessToken: apiMocks.getAccessToken,
  threadsApi: {
    list: apiMocks.listThreads,
    listStale: apiMocks.listStaleThreads,
  },
  sessionApi: {
    getCurrent: apiMocks.getCurrentSession,
  },
}))

import { threadsApi } from '../services/api'
import {
  clearCoalescedReads,
  coalesceRead,
  installApiReadCoalescing,
} from '../services/api-read-coalescing'

const emptyThreadResponse: ThreadListResponse = {
  threads: [],
  total_count: 0,
  page_size: 200,
  next_page_token: null,
}

describe('API read coalescing', () => {
  beforeAll(() => {
    installApiReadCoalescing()
  })

  beforeEach(() => {
    clearCoalescedReads()
    vi.clearAllMocks()
    apiMocks.getAccessToken.mockReturnValue('token-a')
  })

  it('shares an in-flight thread request with equivalent parameters', async () => {
    let resolveRequest: ((value: ThreadListResponse) => void) | undefined
    const request = new Promise<ThreadListResponse>((resolve) => {
      resolveRequest = resolve
    })
    apiMocks.listThreads.mockReturnValue(request)

    const first = threadsApi.list({ search: 'Batman', page_size: 200 })
    const second = threadsApi.list({ page_size: 200, search: 'Batman' })

    expect(first).toBe(second)
    expect(apiMocks.listThreads).toHaveBeenCalledTimes(1)

    resolveRequest?.(emptyThreadResponse)
    await Promise.all([first, second])
  })

  it('starts a fresh request after the previous request settles', async () => {
    apiMocks.listThreads.mockResolvedValue(emptyThreadResponse)

    await threadsApi.list({ page_size: 200 })
    await threadsApi.list({ page_size: 200 })

    expect(apiMocks.listThreads).toHaveBeenCalledTimes(2)
  })

  it('does not share reads across authenticated users', async () => {
    let resolveRequest: ((value: ThreadListResponse) => void) | undefined
    const request = new Promise<ThreadListResponse>((resolve) => {
      resolveRequest = resolve
    })
    apiMocks.listThreads.mockReturnValue(request)

    const first = threadsApi.list({ page_size: 200 })
    apiMocks.getAccessToken.mockReturnValue('token-b')
    const second = threadsApi.list({ page_size: 200 })

    expect(first).not.toBe(second)
    expect(apiMocks.listThreads).toHaveBeenCalledTimes(2)

    resolveRequest?.(emptyThreadResponse)
    await Promise.all([first, second])
  })

  it('evicts a failed request so a retry can run', async () => {
    const loader = vi.fn()
      .mockRejectedValueOnce(new Error('temporary failure'))
      .mockResolvedValueOnce('recovered')

    await expect(coalesceRead('retryable', loader)).rejects.toThrow('temporary failure')
    await expect(coalesceRead('retryable', loader)).resolves.toBe('recovered')
    expect(loader).toHaveBeenCalledTimes(2)
  })
})
