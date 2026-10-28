import { useEffect, useRef, useState } from 'react'
import { act, fireEvent, render, screen } from '@testing-library/react'
import { focusManager, QueryClientProvider, useMutation, useQuery } from '@tanstack/react-query'
import type { QueryClient } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { resumeQueriesAfterOutage } from '../query/cacheEffects'
import { createAppQueryClient } from '../query/queryClient'
import { queryKeys } from '../query/queryKeys'
import {
  getQueryRetryBudgetSnapshot,
  markAuthDegraded,
  markAuthRecovered,
  resetQueryRetryBudget,
} from '../query/outageRetryBudget'

/**
 * Transport-level regression coverage for #4271.
 *
 * Every assertion counts transport calls, not React renders, so the request
 * fan-out is measured directly. Before this change each of three concurrent
 * 503 queries retried itself three times: 3 initial + 9 retries = 12 requests
 * per navigation, repeated on every window focus. The bounded budget now keeps
 * one burst to 5 requests and stops completely after the shared probe fails.
 */

interface Transport {
  calls: string[]
  fetch: (key: string) => Promise<unknown>
  respondWith: (handler: (key: string) => Promise<unknown>) => void
}

function createTransport(initial: (key: string) => Promise<unknown>): Transport {
  let handler = initial
  const calls: string[] = []
  return {
    calls,
    fetch: (key) => {
      calls.push(key)
      return handler(key)
    },
    respondWith: (next) => {
      handler = next
    },
  }
}

function httpError(status: number): Error {
  return Object.assign(new Error(`HTTP ${status}`), {
    isAxiosError: true as const,
    response: { status, data: {} },
  })
}

function QueryProbe({
  name,
  fetcher,
  refetchOnWindowFocus = false,
}: {
  name: string
  fetcher: () => Promise<unknown>
  refetchOnWindowFocus?: boolean
}) {
  const { isError } = useQuery({
    queryKey: ['outage-test', name],
    queryFn: fetcher,
    refetchOnWindowFocus: refetchOnWindowFocus ? 'always' : false,
  })
  return <output data-testid={`status-${name}`}>{isError ? 'error' : 'ok'}</output>
}

function BoundariesProbe({ fetcher }: { fetcher: () => Promise<unknown> }) {
  const { data, isError } = useQuery({
    queryKey: queryKeys.dependencies.readingBoundaries([11, 22]),
    queryFn: fetcher,
  })
  return (
    <output data-testid="boundaries">
      {isError ? 'error' : JSON.stringify(data ?? null)}
    </output>
  )
}

function MutationProbe({ mutationFn }: { mutationFn: () => Promise<unknown> }) {
  const mutation = useMutation({ mutationFn })
  const started = useRef(false)
  useEffect(() => {
    if (started.current) return
    started.current = true
    mutation.mutate()
  }, [mutation])
  return <output data-testid="mutation">{mutation.isError ? 'error' : 'ok'}</output>
}

const RAPID_NAVIGATION_SCREENS = 4

function NavigableProbes({ transport }: { transport: Transport }) {
  const [screenIndex, setScreenIndex] = useState(0)
  const name = `screen-${screenIndex}`
  return (
    <>
      <QueryProbe name={name} fetcher={() => transport.fetch(name)} />
      <button
        type="button"
        onClick={() => setScreenIndex((current) => (
          current + 1 < RAPID_NAVIGATION_SCREENS ? current + 1 : current
        ))}
      >
        navigate
      </button>
    </>
  )
}

function renderWithClient(client: QueryClient, children: React.ReactNode) {
  return render(<QueryClientProvider client={client}>{children}</QueryClientProvider>)
}

async function flushMicrotasks(): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0)
  })
}

async function advance(ms: number): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
}

function countKey(transport: Transport, key: string): number {
  return transport.calls.filter((call) => call === key).length
}

describe('query outage retry budget (#4271)', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    resetQueryRetryBudget()
    focusManager.setFocused(undefined)
  })

  afterEach(() => {
    focusManager.setFocused(undefined)
    vi.useRealTimers()
  })

  it('bounds a concurrent 503 burst and never polls after the shared probe fails', async () => {
    const transport = createTransport(async () => {
      throw httpError(503)
    })
    const client = createAppQueryClient()
    renderWithClient(
      client,
      <>
        <QueryProbe name="a" fetcher={() => transport.fetch('a')} />
        <QueryProbe name="b" fetcher={() => transport.fetch('b')} />
        <QueryProbe name="c" fetcher={() => transport.fetch('c')} />
      </>,
    )

    await flushMicrotasks()
    expect(transport.calls).toEqual(['a', 'b', 'c'])

    // The first query's ordinary retry fires at the 1s backoff, before the
    // shared probe's 4-second deadline.
    await advance(1_000)
    expect(transport.calls).toEqual(['a', 'b', 'c', 'a'])

    // Probe timing: the shared probe must not fire before its 4-second delay.
    await advance(2_900)
    expect(transport.calls).toEqual(['a', 'b', 'c', 'a'])

    // Advance past the probe deadline and allow the shared probe to fire.
    await advance(500)
    expect(transport.calls).toEqual(['a', 'b', 'c', 'a', 'b'])

    await advance(30_000 - 4_400)
    // 3 initial requests + 1 ordinary retry queued before the outage was
    // recognized + 1 shared probe. Before the budget this burst cost 12
    // requests.
    expect(transport.calls).toEqual(['a', 'b', 'c', 'a', 'b'])
    expect(screen.getByTestId('status-a')).toHaveTextContent('error')

    await advance(120_000)
    expect(transport.calls).toHaveLength(5)
    expect(getQueryRetryBudgetSnapshot()).toMatchObject({
      outageActive: true,
      probeRetriesUsed: 1,
    })
  })

  it('recovers from one transient 503 without declaring an outage', async () => {
    let attempts = 0
    const transport = createTransport(async () => {
      attempts += 1
      if (attempts === 1) {
        throw httpError(503)
      }
      return { ok: true }
    })
    const client = createAppQueryClient()
    renderWithClient(client, <QueryProbe name="only" fetcher={() => transport.fetch('only')} />)

    await flushMicrotasks()
    expect(transport.calls).toEqual(['only'])
    expect(getQueryRetryBudgetSnapshot()).toMatchObject({ outageActive: false })

    await advance(1_100)
    expect(transport.calls).toEqual(['only', 'only'])
    expect(screen.getByTestId('status-only')).toHaveTextContent('ok')
  })

  it('never retries a 401 and leaves the auth path to the axios interceptor', async () => {
    const transport = createTransport(async () => {
      throw httpError(401)
    })
    const client = createAppQueryClient()
    renderWithClient(client, <QueryProbe name="auth" fetcher={() => transport.fetch('auth')} />)

    await flushMicrotasks()
    await advance(60_000)

    expect(transport.calls).toEqual(['auth'])
    expect(getQueryRetryBudgetSnapshot()).toMatchObject({
      outageActive: false,
      recentTransientFailures: 0,
    })
  })

  it('does not retry non-idempotent mutations', async () => {
    const transport = createTransport(async () => {
      throw httpError(503)
    })
    const client = createAppQueryClient()
    renderWithClient(client, <MutationProbe mutationFn={() => transport.fetch('write')} />)

    await flushMicrotasks()
    await advance(60_000)

    expect(transport.calls).toEqual(['write'])
  })

  it('charges repeated tab focus one request per distinct key, with zero retries during the outage', async () => {
    const transport = createTransport(async () => {
      throw httpError(503)
    })
    const client = createAppQueryClient()
    renderWithClient(
      client,
      <>
        <QueryProbe name="a" fetcher={() => transport.fetch('a')} refetchOnWindowFocus />
        <QueryProbe name="b" fetcher={() => transport.fetch('b')} refetchOnWindowFocus />
        <QueryProbe name="c" fetcher={() => transport.fetch('c')} refetchOnWindowFocus />
      </>,
    )

    await flushMicrotasks()
    await advance(30_000)
    expect(transport.calls).toHaveLength(5)

    // Returning to the tab is a user action: one request per active key, no
    // retry multiplier. Focus while the tab is already focused is a no-op.
    await act(async () => {
      focusManager.setFocused(true)
    })
    await advance(30_000)
    expect(transport.calls).toHaveLength(8)

    await act(async () => {
      focusManager.setFocused(false)
      focusManager.setFocused(true)
    })
    await advance(30_000)
    expect(transport.calls).toHaveLength(11)
  })

  it('charges rapid navigation one request per new key and none afterwards', async () => {
    const transport = createTransport(async () => {
      throw httpError(503)
    })
    const client = createAppQueryClient()
    renderWithClient(client, <NavigableProbes transport={transport} />)

    await flushMicrotasks()
    expect(transport.calls).toEqual(['screen-0'])

    for (const expected of ['screen-1', 'screen-2', 'screen-3']) {
      fireEvent.click(screen.getByText('navigate'))
      await flushMicrotasks()
      expect(countKey(transport, expected)).toBe(1)
    }

    await advance(60_000)

    // One request per visited screen, and nothing afterwards. The screen that
    // owned the queued probe unmounted with it, which cancels the probe rather
    // than letting a background timer outlive the screen; navigation itself is
    // what retries against a recovered backend.
    expect(transport.calls).toHaveLength(4)
    expect(countKey(transport, 'screen-0')).toBe(1)
    expect(countKey(transport, 'screen-1')).toBe(1)
    expect(countKey(transport, 'screen-2')).toBe(1)
    expect(countKey(transport, 'screen-3')).toBe(1)
  })

  it('refetches each failed key once on recovery, not once per observer', async () => {
    const transport = createTransport(async () => {
      throw httpError(503)
    })
    const client = createAppQueryClient()
    renderWithClient(
      client,
      <>
        <QueryProbe name="a" fetcher={() => transport.fetch('a')} />
        <QueryProbe name="a" fetcher={() => transport.fetch('a')} />
        <QueryProbe name="b" fetcher={() => transport.fetch('b')} />
      </>,
    )

    await flushMicrotasks()
    await advance(30_000)
    expect(countKey(transport, 'a')).toBe(2)
    expect(countKey(transport, 'b')).toBe(2)

    transport.respondWith(async () => ({ ok: true }))
    await act(async () => {
      await resumeQueriesAfterOutage(client)
    })
    await flushMicrotasks()

    expect(countKey(transport, 'a')).toBe(3)
    expect(countKey(transport, 'b')).toBe(3)
    expect(screen.getAllByTestId('status-a')).toHaveLength(2)
    expect(screen.getAllByTestId('status-a')[0]).toHaveTextContent('ok')
    expect(screen.getByTestId('status-b')).toHaveTextContent('ok')
    expect(getQueryRetryBudgetSnapshot()).toMatchObject({ outageActive: false })
  })

  it('resumes failed keys automatically from the first success after the outage', async () => {
    const transport = createTransport(async () => {
      throw httpError(503)
    })
    const client = createAppQueryClient()
    renderWithClient(
      client,
      <>
        <QueryProbe name="a" fetcher={() => transport.fetch('a')} />
        <QueryProbe name="b" fetcher={() => transport.fetch('b')} />
      </>,
    )

    await flushMicrotasks()
    await advance(30_000)
    // 2 initial + 1 retry queued before the outage was recognized + 1 probe.
    expect(transport.calls).toEqual(['a', 'b', 'a', 'b'])

    transport.respondWith(async () => ({ ok: true }))
    await act(async () => {
      // Any successful request ends the outage — here a route-style prefetch.
      // No component calls resumeQueriesAfterOutage itself.
      await client.fetchQuery({
        queryKey: queryKeys.roll.bootstrap(),
        queryFn: () => transport.fetch('recovery'),
      })
    })
    await flushMicrotasks()

    expect(countKey(transport, 'recovery')).toBe(1)
    expect(countKey(transport, 'a')).toBe(3)
    expect(countKey(transport, 'b')).toBe(3)
    expect(screen.getByTestId('status-a')).toHaveTextContent('ok')
    expect(screen.getByTestId('status-b')).toHaveTextContent('ok')
    expect(getQueryRetryBudgetSnapshot()).toMatchObject({ outageActive: false })
  })

  it('suppresses retries while auth is degraded and resumes once after recovery', async () => {
    const transport = createTransport(async () => {
      throw httpError(503)
    })
    const client = createAppQueryClient()
    markAuthDegraded()
    renderWithClient(
      client,
      <>
        <QueryProbe name="a" fetcher={() => transport.fetch('a')} />
        <QueryProbe name="b" fetcher={() => transport.fetch('b')} />
      </>,
    )

    await flushMicrotasks()
    expect(transport.calls).toEqual(['a', 'b'])

    await advance(120_000)
    // AuthProvider owns the auth probe; query observers add no retries.
    expect(transport.calls).toEqual(['a', 'b'])

    transport.respondWith(async () => ({ ok: true }))
    expect(markAuthRecovered()).toBe(true)
    await act(async () => {
      await resumeQueriesAfterOutage(client)
    })

    expect(transport.calls).toEqual(['a', 'b', 'a', 'b'])
    await flushMicrotasks()
    expect(screen.getByTestId('status-a')).toHaveTextContent('ok')
    expect(screen.getByTestId('status-b')).toHaveTextContent('ok')
    expect(getQueryRetryBudgetSnapshot()).toMatchObject({
      authDegraded: false,
      outageActive: false,
    })
  })

  it('serves fresh reading boundaries after a mutation invalidated them during the outage', async () => {
    const transport = createTransport(async () => {
      throw httpError(503)
    })
    const client = createAppQueryClient()
    renderWithClient(client, <BoundariesProbe fetcher={() => transport.fetch('boundaries')} />)

    await flushMicrotasks()
    await advance(30_000)
    expect(screen.getByTestId('boundaries')).toHaveTextContent('error')

    // A rating/issue mutation invalidates dependency reads while the backend is
    // down; the invalidation request fails and the key stays in error state.
    await act(async () => {
      await client.invalidateQueries({ queryKey: queryKeys.dependencies.all }).catch(() => undefined)
    })
    await flushMicrotasks()
    expect(screen.getByTestId('boundaries')).toHaveTextContent('error')

    transport.respondWith(async () => ({
      boundaries: [{ thread_id: 11, available_next: 3 }],
    }))
    await act(async () => {
      await resumeQueriesAfterOutage(client)
    })
    await flushMicrotasks()

    expect(screen.getByTestId('boundaries')).toHaveTextContent(
      JSON.stringify({ boundaries: [{ thread_id: 11, available_next: 3 }] }),
    )
  })
})
