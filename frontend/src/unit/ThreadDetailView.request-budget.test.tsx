/**
 * Request-budget regression for the Thread detail route (#4501).
 *
 * The page owns five records: canonical reading boundaries, the thread
 * detail, connected threads, effective tags, and crossover groups. The
 * crossover batch used to wait for the thread-detail response even though the
 * route already declares the id; it now reads in parallel. The closed tag
 * editor must not add the usable-tag catalog request.
 */
import { render, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import type { ReactNode } from 'react'
import { describe, expect, it } from 'vitest'
import { ToastProvider } from '../contexts/ToastProvider'
import { BugReportRestoreProvider } from '../contexts/BugReportRestoreContext'
import { setDefaultHttpClient } from '../services/httpClient'
import { createHttpClientStub } from './httpClientStub'
import ThreadDetailView from '../pages/ThreadDetailView'

type JsonValue =
  | string
  | number
  | boolean
  | null
  | undefined
  | JsonValue[]
  | { [key: string]: JsonValue }

type RecordedCall = {
  method: string
  url: string
  params?: Record<string, string | number>
  data?: JsonValue
}

type Responder = (call: RecordedCall) => JsonValue | Promise<JsonValue>

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((promiseResolve) => {
    resolve = promiseResolve
  })
  return { promise, resolve }
}

function makeRecordingClient(responder: Responder) {
  const calls: RecordedCall[] = []
  const client = createHttpClientStub()
  const respond = (
    method: string,
    url: string,
    params?: Record<string, string | number>,
    data?: JsonValue,
  ) => {
    const call = { method, url, params, data }
    calls.push(call)
    return Promise.resolve(responder(call))
  }
  client.get.mockImplementation(
    (url: string, config?: { params?: Record<string, string | number> }) =>
      respond('GET', url, config?.params),
  )
  client.delete.mockImplementation(
    (url: string, config?: { params?: Record<string, string | number> }) =>
      respond('DELETE', url, config?.params),
  )
  client.post.mockImplementation((url: string, data?: JsonValue) =>
    respond('POST', url, undefined, data),
  )
  client.put.mockImplementation((url: string, data?: JsonValue) =>
    respond('PUT', url, undefined, data),
  )
  client.patch.mockImplementation((url: string, data?: JsonValue) =>
    respond('PATCH', url, undefined, data),
  )
  return { calls, client }
}

const thread = {
  id: 42,
  title: 'Saga',
  format: 'Comics',
  issues_remaining: 5,
  queue_position: 1,
  status: 'active',
  total_issues: null,
  notes: null,
  blocking_reasons: [],
  next_unread_issue_number: '1',
}

function renderThread(): ReactNode {
  return (
    <MemoryRouter initialEntries={['/thread/42']}>
      <BugReportRestoreProvider>
        <ToastProvider>
          <Routes>
            <Route path="/thread/:id" element={<ThreadDetailView />} />
          </Routes>
        </ToastProvider>
      </BugReportRestoreProvider>
    </MemoryRouter>
  )
}

const defaultHandler: Responder = (call) => {
  if (call.url === '/v2/reading-boundaries') {
    return { threads: { 42: { state: 'unavailable' } } }
  }
  if (call.url === '/v1/threads/42') return thread
  if (call.url === '/v1/threads/42/connected') {
    return { thread_id: 42, connected_threads: [] }
  }
  if (call.url === '/v1/threads/groups:batch') return {}
  if (call.url === '/v1/tags/effective/thread/42/') {
    return { target_type: 'Thread', target_id: 42, direct_tags: [], effective_tags: [] }
  }
  if (call.url === '/v1/tags/') return { tags: [] }
  if (call.url === '/v1/threads:getBlockingInfo') {
    return {
      threads: {
        42: { is_blocked: false, blocking_reasons: [], blocking_dependencies: [] },
      },
    }
  }
  return {}
}

function requestKey(call: RecordedCall): string {
  return `${call.method} ${call.url}`
}

describe('Thread detail request budget', () => {
  it('cold-loads one read per record and never reads the closed tag catalog', async () => {
    const { calls, client } = makeRecordingClient(defaultHandler)
    setDefaultHttpClient(client)

    const { unmount } = render(renderThread())

    await waitFor(() =>
      expect(calls.some((call) => call.url === '/v1/threads/groups:batch')).toBe(true),
    )
    await waitFor(() =>
      expect(calls.some((call) => call.url === '/v1/threads/42/connected')).toBe(true),
    )
    await new Promise((resolve) => setTimeout(resolve, 100))

    expect(new Set(calls.map(requestKey))).toEqual(
      new Set([
        'POST /v2/reading-boundaries',
        'GET /v1/threads/42',
        'GET /v1/threads/42/connected',
        'GET /v1/tags/effective/thread/42/',
        'POST /v1/threads/groups:batch',
        'POST /v1/threads:getBlockingInfo',
      ]),
    )
    expect(calls.some((call) => call.url === '/v1/tags/')).toBe(false)

    // Warm remount inside the query stale window must reuse the cache.
    unmount()
    const callCount = calls.length
    render(renderThread())
    await new Promise((resolve) => setTimeout(resolve, 100))
    expect(calls.length).toBe(callCount)
  })

  it('reads crossover groups in parallel with the thread detail', async () => {
    const threadResponse = deferred<typeof thread>()
    const { calls, client } = makeRecordingClient((call) => {
      if (call.url === '/v1/threads/42') return threadResponse.promise
      return defaultHandler(call)
    })
    setDefaultHttpClient(client)

    render(renderThread())

    // The route id is authoritative: the batch must start while the thread
    // detail is still unresolved.
    await waitFor(() =>
      expect(calls.some((call) => call.url === '/v1/threads/groups:batch')).toBe(true),
    )
    expect(calls.some((call) => call.url === '/v1/threads/42')).toBe(true)

    threadResponse.resolve(thread)
    await waitFor(() =>
      expect(calls.some((call) => call.url === '/v1/threads/42/connected')).toBe(true),
    )
  })
})
