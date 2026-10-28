import { act, render } from '@testing-library/react'
import { focusManager, QueryClientProvider, useQuery } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createAppQueryClient } from '../query/queryClient'
import {
  getQueryRetryBudgetSnapshot,
  resetQueryRetryBudget,
} from '../query/outageRetryBudget'

function httpError(status: number): Error {
  return Object.assign(new Error(`HTTP ${status}`), {
    isAxiosError: true as const,
    response: { status, data: {} },
  })
}

function Probe({ name, fetcher }: { name: string; fetcher: () => Promise<unknown> }) {
  useQuery({ queryKey: ['debug', name], queryFn: fetcher, refetchOnWindowFocus: false })
  return <span data-testid={name}>{name}</span>
}

async function flush(): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0)
  })
}

async function advance(ms: number): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
}

describe('debug outage behavior', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    resetQueryRetryBudget()
    focusManager.setFocused(undefined)
  })

  afterEach(() => {
    focusManager.setFocused(undefined)
    vi.useRealTimers()
  })

  it('logs call sequence for 3 concurrent 503s', async () => {
    const calls: string[] = []
    const transport = async (key: string) => {
      calls.push(key)
      console.log(`CALL ${key} at ${Date.now()}, total calls so far: ${calls.length}`)
      throw httpError(503)
    }
    const client = createAppQueryClient()
    render(
      <QueryClientProvider client={client}>
        <Probe name="a" fetcher={() => transport('a')} />
        <Probe name="b" fetcher={() => transport('b')} />
        <Probe name="c" fetcher={() => transport('c')} />
      </QueryClientProvider>,
    )

    await flush()
    console.log(`AFTER FLUSH: calls=${JSON.stringify(calls)}`)
    console.log(`SNAPSHOT: ${JSON.stringify(getQueryRetryBudgetSnapshot())}`)

    await advance(1_000)
    console.log(`AFTER 1000ms: calls=${JSON.stringify(calls)}`)
    console.log(`SNAPSHOT: ${JSON.stringify(getQueryRetryBudgetSnapshot())}`)

    await advance(2_900)
    console.log(`AFTER 3900ms: calls=${JSON.stringify(calls)}`)
    console.log(`SNAPSHOT: ${JSON.stringify(getQueryRetryBudgetSnapshot())}`)

    await advance(200)
    console.log(`AFTER 4100ms: calls=${JSON.stringify(calls)}`)
    console.log(`SNAPSHOT: ${JSON.stringify(getQueryRetryBudgetSnapshot())}`)

    expect(true).toBe(true)
  })
})
