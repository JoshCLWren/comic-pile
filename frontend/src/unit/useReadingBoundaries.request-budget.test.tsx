/**
 * Cross-route request budget for the deployment-wide boundary evaluator (#4501).
 *
 * The first unavailable response is the capability discovery. Later route keys,
 * warm remounts, and invalidations inside its freshness window must use legacy
 * blocking directly instead of repeating the canonical batch. Expiry and auth
 * transitions must permit a fresh discovery after a deployment or account change.
 */
import { QueryClientProvider, type QueryClient } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import type { PropsWithChildren } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useThreadBlockingInfo } from '../hooks/useDependencies'
import { useReadingBoundaries } from '../hooks/useReadingBoundaries'
import { clearSessionCache } from '../query/cacheEffects'
import { createAppQueryClient } from '../query/queryClient'
import { queryKeys } from '../query/queryKeys'
import { setDefaultHttpClient } from '../services/httpClient'
import {
  createRequestRecorder,
  requestCounts,
  requestedThreadIds,
} from './requestRecorder'

function wrapperFor(client: QueryClient) {
  return function Wrapper({ children }: PropsWithChildren) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

function useBoundaryAndLegacyFallback(threadId: number) {
  const boundary = useReadingBoundaries([threadId])
  const unavailable =
    !boundary.isPending &&
    !boundary.isError &&
    (boundary.data?.evaluator === 'unavailable' ||
      boundary.data?.threads[threadId]?.state === 'unavailable')
  const legacy = useThreadBlockingInfo(unavailable ? threadId : null)
  return { boundary, legacy }
}

describe('reading boundary evaluator request budget', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('discovers unavailable once, then sends only legacy reads across keys and invalidation', async () => {
    const client = createAppQueryClient()
    const { calls, client: httpClient } = createRequestRecorder((call) => {
      if (call.url === '/v2/reading-boundaries') {
        const threads = Object.fromEntries(requestedThreadIds(call).map((id) => [id, {
          thread_id: id,
          state: 'unavailable',
          summary: 'The canonical evaluator is unavailable.',
          next: null,
          blockers: [],
        }]))
        return { threads, evaluator: 'unavailable' }
      }
      if (call.url === '/v1/threads:getBlockingInfo') {
        const threads = Object.fromEntries(requestedThreadIds(call).map((id) => [id, {
          is_blocked: false,
          blocking_reasons: [],
          blocking_dependencies: [],
        }]))
        return { threads }
      }
      return {}
    })
    setDefaultHttpClient(httpClient)
    const wrapper = wrapperFor(client)

    const queue = renderHook(() => useBoundaryAndLegacyFallback(7), { wrapper })
    await waitFor(() => expect(queue.result.current.legacy.data?.threads[7]).toBeDefined())
    queue.unmount()

    const thread = renderHook(() => useBoundaryAndLegacyFallback(8), { wrapper })
    await waitFor(() => expect(thread.result.current.legacy.data?.threads[8]).toBeDefined())
    expect(requestCounts(calls)).toEqual({
      'POST /v2/reading-boundaries': 1,
      'POST /v1/threads:getBlockingInfo': 2,
    })
    expect(calls.filter((call) => call.url === '/v2/reading-boundaries').map(requestedThreadIds)).toEqual([[7]])
    expect(calls.filter((call) => call.url === '/v1/threads:getBlockingInfo').map(requestedThreadIds)).toEqual([[7], [8]])

    const beforeWarmRemount = calls.length
    thread.unmount()
    const warm = renderHook(() => useBoundaryAndLegacyFallback(8), { wrapper })
    await waitFor(() => expect(warm.result.current.legacy.data?.threads[8]).toBeDefined())
    expect(calls).toHaveLength(beforeWarmRemount)

    await client.invalidateQueries({ queryKey: queryKeys.dependencies.readingBoundariesAll() })
    await client.invalidateQueries({ queryKey: queryKeys.dependencies.blockingBatchAll() })
    await waitFor(() => expect(requestCounts(calls)['POST /v1/threads:getBlockingInfo']).toBe(3))
    expect(requestCounts(calls)).toEqual({
      'POST /v2/reading-boundaries': 1,
      'POST /v1/threads:getBlockingInfo': 3,
    })
  })

  it('rediscovers an expired unavailable capability instead of caching it forever', async () => {
    let now = 1_000_000
    vi.spyOn(Date, 'now').mockImplementation(() => now)
    const client = createAppQueryClient()
    const { calls, client: httpClient } = createRequestRecorder((call) => {
      if (call.url === '/v2/reading-boundaries') {
        const enabled = requestedThreadIds(call).includes(8)
        const threads = Object.fromEntries(requestedThreadIds(call).map((id) => [id, {
          thread_id: id,
          state: enabled ? 'available' : 'unavailable',
          summary: enabled ? 'Available now.' : 'The canonical evaluator is unavailable.',
          next: null,
          blockers: [],
        }]))
        return { threads, evaluator: enabled ? 'enabled' : 'unavailable' }
      }
      return {}
    })
    setDefaultHttpClient(httpClient)
    const wrapper = wrapperFor(client)

    const beforeRollout = renderHook(() => useReadingBoundaries([7]), { wrapper })
    await waitFor(() => expect(beforeRollout.result.current.data?.evaluator).toBe('unavailable'))
    beforeRollout.unmount()

    now += 30_001
    const afterRollout = renderHook(() => useReadingBoundaries([8]), { wrapper })
    await waitFor(() => expect(afterRollout.result.current.isPending).toBe(false))

    expect(afterRollout.result.current.data?.evaluator).toBe('enabled')
    expect(afterRollout.result.current.data?.threads[8]?.state).toBe('available')
    expect(requestCounts(calls)).toEqual({ 'POST /v2/reading-boundaries': 2 })
    expect(calls.map(requestedThreadIds)).toEqual([[7], [8]])
  })

  it('rediscovers the evaluator after an auth-session cache clear', async () => {
    const client = createAppQueryClient()
    const { calls, client: httpClient } = createRequestRecorder((call) => {
      if (call.url === '/v2/reading-boundaries') {
        const threads = Object.fromEntries(requestedThreadIds(call).map((id) => [id, {
          thread_id: id,
          state: 'unavailable',
          summary: 'The canonical evaluator is unavailable.',
          next: null,
          blockers: [],
        }]))
        return { threads, evaluator: 'unavailable' }
      }
      return {}
    })
    setDefaultHttpClient(httpClient)
    const wrapper = wrapperFor(client)

    const previousAccount = renderHook(() => useReadingBoundaries([7]), { wrapper })
    await waitFor(() => expect(previousAccount.result.current.data?.evaluator).toBe('unavailable'))
    previousAccount.unmount()

    clearSessionCache(client)

    const nextAccount = renderHook(() => useReadingBoundaries([8]), { wrapper })
    await waitFor(() => expect(nextAccount.result.current.data?.evaluator).toBe('unavailable'))
    expect(requestCounts(calls)).toEqual({ 'POST /v2/reading-boundaries': 2 })
    expect(calls.map(requestedThreadIds)).toEqual([[7], [8]])
  })

  it('keeps fetching canonical explanations for each key while the evaluator is enabled', async () => {
    const client = createAppQueryClient()
    const { calls, client: httpClient } = createRequestRecorder((call) => {
      if (call.url === '/v2/reading-boundaries') {
        const threads = Object.fromEntries(requestedThreadIds(call).map((id) => [id, {
          thread_id: id,
          state: 'available',
          summary: 'Available now.',
          next: null,
          blockers: [],
        }]))
        return { threads, evaluator: 'enabled' }
      }
      return {}
    })
    setDefaultHttpClient(httpClient)
    const wrapper = wrapperFor(client)

    const first = renderHook(() => useReadingBoundaries([7]), { wrapper })
    await waitFor(() => expect(first.result.current.data?.evaluator).toBe('enabled'))
    first.unmount()
    const second = renderHook(() => useReadingBoundaries([8]), { wrapper })
    await waitFor(() => expect(second.result.current.data?.evaluator).toBe('enabled'))

    expect(requestCounts(calls)).toEqual({ 'POST /v2/reading-boundaries': 2 })
    expect(calls.map(requestedThreadIds)).toEqual([[7], [8]])
  })
})
