/**
 * Request-budget regression for the Thread detail route (#4501).
 *
 * The page owns canonical reading boundaries, the thread detail, connected
 * threads, effective tags, and crossover groups. The crossover batch used to
 * wait for the thread-detail response even though the route already declares
 * the id; it now reads in parallel. The closed tag editor must not add the
 * usable-tag catalog request.
 *
 * Two deployment shapes are asserted because the legacy blocking fallback only
 * runs when the canonical evaluator reports `unavailable`:
 * - canonical available: 6 reads before, 5 after (catalog removed)
 * - Option-E off (`unavailable`): 7 reads before, 6 after (catalog removed)
 */
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom'
import type { ReactNode } from 'react'
import { describe, expect, it } from 'vitest'
import { ToastProvider } from '../contexts/ToastProvider'
import { BugReportRestoreProvider } from '../contexts/BugReportRestoreContext'
import { setDefaultHttpClient } from '../services/httpClient'
import ThreadDetailView from '../pages/ThreadDetailView'
import {
  createRequestRecorder,
  requestedThreadIds,
  requestCounts,
  type RecordedCall,
  type Responder,
} from './requestRecorder'

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((promiseResolve) => {
    resolve = promiseResolve
  })
  return { promise, resolve }
}

const THREADS = {
  42: {
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
  },
  43: {
    id: 43,
    title: 'Monstress',
    format: 'Comics',
    issues_remaining: 2,
    queue_position: 2,
    status: 'active',
    total_issues: null,
    notes: null,
    blocking_reasons: [],
    next_unread_issue_number: '1',
  },
}

const CROSSOVERS = {
  42: [{ id: 420, name: 'Group 42' }],
  43: [{ id: 430, name: 'Group 43' }],
}

type BoundaryState = 'available' | 'unavailable'

type BlockingSummary = {
  is_blocked: boolean
  blocking_reasons: string[]
  blocking_dependencies: string[]
}

function boundaryBatch(state: BoundaryState, ids: number[]) {
  const threads: Record<string, { state: BoundaryState }> = {}
  for (const id of ids) threads[id] = { state }
  return { threads }
}

function makeHandler(state: BoundaryState): Responder {
  return (call: RecordedCall) => {
    if (call.url === '/v2/reading-boundaries') {
      return boundaryBatch(state, requestedThreadIds(call))
    }
    if (call.url === '/v1/threads/42') return THREADS[42]
    if (call.url === '/v1/threads/43') return THREADS[43]
    if (call.url === '/v1/threads/42/connected' || call.url === '/v1/threads/43/connected') {
      const id = call.url.includes('/43/') ? 43 : 42
      return { thread_id: id, connected_threads: [] }
    }
    if (call.url === '/v1/threads/groups:batch') {
      const groups: Record<string, { id: number; name: string }[]> = {}
      for (const id of requestedThreadIds(call)) groups[id] = id === 42 ? CROSSOVERS[42] : id === 43 ? CROSSOVERS[43] : []
      return groups
    }
    if (call.url === '/v1/tags/effective/thread/42/') {
      return { target_type: 'Thread', target_id: 42, direct_tags: [], effective_tags: [] }
    }
    if (call.url === '/v1/tags/effective/thread/43/') {
      return { target_type: 'Thread', target_id: 43, direct_tags: [], effective_tags: [] }
    }
    if (call.url === '/v1/tags/') return { tags: [] }
    if (call.url === '/v1/threads:getBlockingInfo') {
      const threads: Record<string, BlockingSummary> = {}
      for (const id of requestedThreadIds(call)) {
        threads[id] = { is_blocked: false, blocking_reasons: [], blocking_dependencies: [] }
      }
      return { threads }
    }
    return {}
  }
}

function renderThread(path = '/thread/42'): ReactNode {
  return (
    <MemoryRouter initialEntries={[path]}>
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

function NavigateTo43() {
  const navigate = useNavigate()
  return (
    <button type="button" onClick={() => navigate('/thread/43')}>
      open 43
    </button>
  )
}

function renderThreadWithNavigation(): ReactNode {
  return (
    <MemoryRouter initialEntries={['/thread/42']}>
      <BugReportRestoreProvider>
        <ToastProvider>
          <Routes>
            <Route
              path="/thread/:id"
              element={
                <>
                  <ThreadDetailView />
                  <NavigateTo43 />
                </>
              }
            />
          </Routes>
        </ToastProvider>
      </BugReportRestoreProvider>
    </MemoryRouter>
  )
}

function groupsCalls(calls: RecordedCall[]): RecordedCall[] {
  return calls.filter((call) => call.url === '/v1/threads/groups:batch')
}

describe('Thread detail request budget', () => {
  it('Option-E off: cold-loads each read exactly once and skips the closed tag catalog', async () => {
    const { calls, client } = createRequestRecorder(makeHandler('unavailable'))
    setDefaultHttpClient(client)

    const { unmount } = render(renderThread())

    await waitFor(() => expect(groupsCalls(calls)).toHaveLength(1))
    await waitFor(() =>
      expect(calls.some((call) => call.url === '/v1/threads:getBlockingInfo')).toBe(true),
    )
    await new Promise((resolve) => setTimeout(resolve, 100))

    expect(requestCounts(calls)).toEqual({
      'POST /v2/reading-boundaries': 1,
      'GET /v1/threads/42': 1,
      'GET /v1/threads/42/connected': 1,
      'GET /v1/tags/effective/thread/42/': 1,
      'POST /v1/threads/groups:batch': 1,
      'POST /v1/threads:getBlockingInfo': 1,
    })
    expect(calls.some((call) => call.url === '/v1/tags/')).toBe(false)

    // Warm remount inside the query stale window must reuse the cache.
    unmount()
    const callCount = calls.length
    render(renderThread())
    await new Promise((resolve) => setTimeout(resolve, 100))
    expect(calls).toHaveLength(callCount)
  })

  it('canonical available: five reads, no legacy blocking probe', async () => {
    const { calls, client } = createRequestRecorder(makeHandler('available'))
    setDefaultHttpClient(client)

    render(renderThread())

    await waitFor(() => expect(groupsCalls(calls)).toHaveLength(1))
    await new Promise((resolve) => setTimeout(resolve, 100))

    expect(requestCounts(calls)).toEqual({
      'POST /v2/reading-boundaries': 1,
      'GET /v1/threads/42': 1,
      'GET /v1/threads/42/connected': 1,
      'GET /v1/tags/effective/thread/42/': 1,
      'POST /v1/threads/groups:batch': 1,
    })
    expect(calls.some((call) => call.url === '/v1/tags/')).toBe(false)
  })

  it('reads crossover groups in parallel with the thread detail', async () => {
    const threadResponse = deferred<typeof THREADS[42]>()
    const handler = makeHandler('available')
    const { calls, client } = createRequestRecorder((call) => {
      if (call.url === '/v1/threads/42') return threadResponse.promise
      return handler(call)
    })
    setDefaultHttpClient(client)

    render(renderThread())

    // The route id is authoritative: the batch must start while the thread
    // detail is still unresolved.
    await waitFor(() => expect(groupsCalls(calls)).toHaveLength(1))
    expect(calls.some((call) => call.url === '/v1/threads/42')).toBe(true)

    threadResponse.resolve(THREADS[42])
    await waitFor(() =>
      expect(calls.some((call) => call.url === '/v1/threads/42/connected')).toBe(true),
    )
    expect(groupsCalls(calls)).toHaveLength(1)
  })

  it('route change 42 to 43 batches only the new id and renders only its groups', async () => {
    const { calls, client } = createRequestRecorder(makeHandler('available'))
    setDefaultHttpClient(client)

    render(renderThreadWithNavigation())

    await waitFor(() => expect(screen.getByText('Group 42')).toBeInTheDocument())
    expect(groupsCalls(calls)).toHaveLength(1)
    expect(requestedThreadIds(groupsCalls(calls)[0])).toEqual([42])

    screen.getByRole('button', { name: 'open 43' }).click()

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Monstress' })).toBeInTheDocument())
    await waitFor(() => expect(groupsCalls(calls)).toHaveLength(2))

    expect(groupsCalls(calls).map(requestedThreadIds)).toEqual([[42], [43]])
    expect(screen.getByText('Group 43')).toBeInTheDocument()
    expect(screen.queryByText('Group 42')).not.toBeInTheDocument()
    expect(
      calls.filter((call) => call.url === '/v1/threads/42'),
    ).toHaveLength(1)
    expect(
      calls.filter((call) => call.url === '/v1/threads/43'),
    ).toHaveLength(1)
  })

  it('unknown thread id batches once and never surfaces a crossover error', async () => {
    const handler = makeHandler('unavailable')
    const { calls, client } = createRequestRecorder((call) => {
      if (call.url === '/v1/threads/999') return Promise.reject(new Error('404'))
      if (call.url === '/v1/threads/groups:batch') return Promise.reject(new Error('404'))
      return handler(call)
    })
    setDefaultHttpClient(client)

    render(renderThread('/thread/999'))

    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'Thread Details' })).toBeInTheDocument(),
    )
    expect(groupsCalls(calls)).toHaveLength(1)
    expect(requestedThreadIds(groupsCalls(calls)[0])).toEqual([999])
    expect(screen.queryByText('Unable to load crossover memberships.')).not.toBeInTheDocument()
  })
})
