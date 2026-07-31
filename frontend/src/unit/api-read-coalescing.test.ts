import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import type { SessionCurrent, ThreadListResponse } from '../types'

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

import { sessionApi, threadsApi } from '../services/api'
import {
  clearCoalescedReads,
  coalesceRead,
  installApiReadCoalescing,
} from '../services/api-read-coalescing'

const emptyThreadResponse: ThreadListResponse = {
  threads: [],
  next_page_token: null,
}

const currentSession: SessionCurrent = {
  id: 1,
  current_die: 20,
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

  it('keeps request keys isolated by access token', async () => {
    const resolvers: Array<(value: ThreadListResponse) => void> = []
    apiMocks.listThreads.mockImplementation(() =>
      new Promise<ThreadListResponse>((resolve) => {
        resolvers.push(resolve)
      })
    )

    const first = threadsApi.list({ page_size: 200 })
    apiMocks.getAccessToken.mockReturnValue('token-b')
    const second = threadsApi.list({ page_size: 200 })

    expect(first).not.toBe(second)
    expect(apiMocks.listThreads).toHaveBeenCalledTimes(2)

    for (const resolve of resolvers) {
      resolve(emptyThreadResponse)
    }
    await Promise.all([first, second])
  })

  it('coalesces stale-thread and current-session reads', async () => {
    let resolveStaleThreads: ((value: []) => void) | undefined
    let resolveCurrentSession: ((value: SessionCurrent) => void) | undefined
    const staleThreadsRequest = new Promise<[]>((resolve) => {
      resolveStaleThreads = resolve
    })
    const currentSessionRequest = new Promise<SessionCurrent>((resolve) => {
      resolveCurrentSession = resolve
    })
    apiMocks.listStaleThreads.mockReturnValue(staleThreadsRequest)
    apiMocks.getCurrentSession.mockReturnValue(currentSessionRequest)

    const firstStale = threadsApi.listStale(45)
    const secondStale = threadsApi.listStale(45)
    const firstSession = sessionApi.getCurrent()
    const secondSession = sessionApi.getCurrent()

    expect(firstStale).toBe(secondStale)
    expect(firstSession).toBe(secondSession)
    expect(apiMocks.listStaleThreads).toHaveBeenCalledTimes(1)
    expect(apiMocks.getCurrentSession).toHaveBeenCalledTimes(1)

    resolveStaleThreads?.([])
    resolveCurrentSession?.(currentSession)
    await Promise.all([firstStale, secondStale, firstSession, secondSession])
  })

  it('does not wrap the API methods more than once', () => {
    const installedThreadsList = threadsApi.list
    const installedStaleThreads = threadsApi.listStale
    const installedCurrentSession = sessionApi.getCurrent

    installApiReadCoalescing()

    expect(threadsApi.list).toBe(installedThreadsList)
    expect(threadsApi.listStale).toBe(installedStaleThreads)
    expect(sessionApi.getCurrent).toBe(installedCurrentSession)
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
