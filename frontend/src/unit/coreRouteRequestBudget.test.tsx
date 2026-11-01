/**
 * Request budgets for the authenticated core views (#4501).
 *
 * Each case mounts the real route component through the real service layer
 * with only the HTTP transport doubled, so the assertions count the exact
 * HTTP method + path + query parameters the browser would send. They fail on
 * needless calls and stay silent for cache-served warm navigation.
 */
import { StrictMode, type ReactNode } from 'react'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { ToastProvider } from '../contexts/ToastProvider'
import { BugReportRestoreProvider } from '../contexts/BugReportRestoreContext'
import { setDefaultHttpClient } from '../services/httpClient'
import { createHttpClientStub } from './httpClientStub'
import { AuthContext } from '../contexts/AuthContext'
import { NavCollapseProvider } from '../contexts/NavCollapseContext'
import type { AuthState } from '../services/authState'
import Navigation from '../components/Navigation'
import { PreferencesSync } from '../hooks/usePreferences'
import QueuePage from '../pages/QueuePage'
import { identityInboxApi } from '../services/api-identity'

vi.mock('../services/api-identity', () => ({
  identityInboxApi: { list: vi.fn() },
}))
import RollPage from '../pages/RollPage'
import HistoryPage from '../pages/HistoryPage'
import SessionPage from '../pages/SessionPage'

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

function key(call: RecordedCall): string {
  const params = call.params
    ? `?${Object.keys(call.params).sort().map((name) => `${name}=${String(call.params?.[name])}`).join('&')}`
    : ''
  return `${call.method} ${call.url}${params}`
}

function Providers({ children }: { children: ReactNode }) {
  return (
    <BugReportRestoreProvider>
      <ToastProvider>{children}</ToastProvider>
    </BugReportRestoreProvider>
  )
}

function renderAt(path: string, element: ReactNode, strict = false): ReactNode {
  const tree = (
    <MemoryRouter initialEntries={[path]}>
      <Providers>{element}</Providers>
    </MemoryRouter>
  )
  return strict ? <StrictMode>{tree}</StrictMode> : tree
}

const session = {
  id: 1,
  user_id: 1,
  started_at: '2026-11-01T00:00:00Z',
  ended_at: null,
  start_die: 6,
  current_die: 6,
  ladder_path: '6',
  snoozed_threads: [],
  pending_thread_id: null,
  pending_thread: null,
  session_mode: null,
}

const queueThreads = [1, 2].map((id) => ({
  id,
  title: `Series ${id}`,
  format: 'Comic',
  issues_remaining: 3,
  total_issues: 3,
  status: 'active',
  is_blocked: false,
  next_unread_issue_number: '1',
  queue_position: id,
  tags: [],
  series_metadata: null,
  comicvine_mapping: null,
  notes: null,
  blocking_reasons: [],
}))

const queueHandler: Responder = (call) => {
  if (call.url === '/v1/sessions/current/') return session
  if (call.url === '/v1/threads/') {
    return { threads: queueThreads, next_page_token: null, active_count: 2 }
  }
  if (call.url === '/v1/threads/excluded/threads') {
    return { threads: [], next_page_token: null, active_count: 0 }
  }
  if (call.url === '/v2/reading-boundaries') {
    return { threads: { 1: { state: 'unavailable' }, 2: { state: 'unavailable' } } }
  }
  if (call.url === '/v1/threads/groups:batch') return {}
  if (call.url === '/v1/threads:getBlockingInfo') {
    return {
      threads: {
        1: { is_blocked: false, blocking_reasons: [], blocking_dependencies: [] },
        2: { is_blocked: false, blocking_reasons: [], blocking_dependencies: [] },
      },
    }
  }
  return {}
}

const bootstrap = {
  session_id: 1,
  user_id: 1,
  current_die: 6,
  manual_die: null,
  pending_thread_id: null,
  last_rolled_result: null,
  session_mode: {
    active_bandwidth: null,
    predicted_bandwidth: null,
    bandwidth_confidence: null,
    bandwidth_source: null,
    bandwidth_version: null,
    active_intent: null,
    predicted_intent: null,
    intent_confidence: null,
    intent_source: null,
    intent_version: null,
    session_mode_correction_guidance: null,
  },
  active_thread: null,
  roll_pool: [],
  snoozed_threads: [],
  snoozed_count: 0,
  skipped_thread_ids: [],
  skipped_threads: [],
  last_read: null,
}

const authState: AuthState = {
  status: 'authenticated',
  isLoading: false,
  user: {
    id: 1,
    username: 'reader',
    email: 'reader@example.com',
    is_admin: false,
  },
  error: null,
  retryCount: 0,
  lastRetryAt: null,
}

function renderShell(): ReactNode {
  return (
    <MemoryRouter initialEntries={['/queue']}>
      <AuthContext.Provider
        value={{
          authState,
          isAuthenticated: true,
          isLoading: false,
          user: authState.user,
          login: async () => undefined,
          logout: () => undefined,
          revalidateSession: async () => undefined,
          recoverSession: async () => undefined,
          retryAuth: async () => undefined,
          clearAuthError: () => undefined,
        }}
      >
        <NavCollapseProvider>
          <BugReportRestoreProvider>
            <ToastProvider>
              <Navigation onBugReportSubmit={async () => undefined} />
              <PreferencesSync isAuthenticated />
            </ToastProvider>
          </BugReportRestoreProvider>
        </NavCollapseProvider>
      </AuthContext.Provider>
    </MemoryRouter>
  )
}

describe('core route request budgets', () => {
  it('authenticated shell cold-loads preferences and inbox status once each', async () => {
    const inboxList = vi.mocked(identityInboxApi.list)
    inboxList.mockReset()
    inboxList.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 1 })
    const { calls, client } = makeRecordingClient((call) => {
      if (call.url === '/v1/users/me/preferences') return { theme: 'classic', user_id: 1 }
      return {}
    })
    setDefaultHttpClient(client)

    render(renderShell())

    await waitFor(() => expect(calls.some((call) => call.url === '/v1/users/me/preferences')).toBe(true))
    await waitFor(() => expect(inboxList).toHaveBeenCalledTimes(1))
    await new Promise((resolve) => setTimeout(resolve, 100))

    expect(new Set(calls.map(key))).toEqual(new Set(['GET /v1/users/me/preferences']))
    expect(inboxList).toHaveBeenCalledWith(0, 1)
  })

  it('Roll cold-loads one bootstrap read, even under StrictMode', async () => {
    const { calls, client } = makeRecordingClient((call) => {
      if (call.url === '/v2/roll/bootstrap') return bootstrap
      return {}
    })
    setDefaultHttpClient(client)

    render(renderAt('/', <RollPage />, true))

    await waitFor(() => expect(calls.some((call) => call.url === '/v2/roll/bootstrap')).toBe(true))
    await new Promise((resolve) => setTimeout(resolve, 100))

    expect(calls).toHaveLength(1)
    expect(calls[0].method).toBe('GET')
    expect(calls[0].url).toBe('/v2/roll/bootstrap')
    expect(calls[0].params?.timezone).toBe(
      Intl.DateTimeFormat().resolvedOptions().timeZone || undefined,
    )
  })

  it('Queue cold-loads each bounded batch once and reuses the cache on warm remount', async () => {
    const { calls, client } = makeRecordingClient(queueHandler)
    setDefaultHttpClient(client)

    const view = render(renderAt('/queue', <QueuePage />))

    await waitFor(() =>
      expect(calls.some((call) => call.url === '/v1/threads:getBlockingInfo')).toBe(true),
    )
    await new Promise((resolve) => setTimeout(resolve, 100))

    expect(new Set(calls.map(key))).toEqual(
      new Set([
        'GET /v1/threads/?page_size=50&sort=position',
        'GET /v1/sessions/current/',
        'GET /v1/threads/excluded/threads?page_size=50&sort=created',
        'POST /v2/reading-boundaries',
        'POST /v1/threads/groups:batch',
        'POST /v1/threads:getBlockingInfo',
      ]),
    )

    view.unmount()
    const warmed = calls.length
    render(renderAt('/queue', <QueuePage />))
    await new Promise((resolve) => setTimeout(resolve, 100))
    expect(calls.length).toBe(warmed)
  })

  it('Queue search commits one request for the final debounced value', async () => {
    const { calls, client } = makeRecordingClient(queueHandler)
    setDefaultHttpClient(client)

    render(renderAt('/queue', <QueuePage />))
    await waitFor(() => expect(calls.some((call) => call.url === '/v1/threads/')).toBe(true))

    const search = screen.getByRole('textbox', { name: 'Search series' })
    for (const value of ['r', 'ro', 'rob', 'robe', 'robert']) {
      fireEvent.change(search, { target: { value } })
    }

    await waitFor(
      () =>
        expect(
          calls.some(
            (call) => call.url === '/v1/threads/' && call.params?.search === 'robert',
          ),
        ).toBe(true),
      { timeout: 2000 },
    )

    const searchCalls = calls.filter(
      (call) => call.url === '/v1/threads/' && call.params?.search != null,
    )
    expect(searchCalls.map((call) => call.params?.search)).toEqual(['robert'])
  })

  it('History cold-loads exactly one session list page', async () => {
    const { calls, client } = makeRecordingClient((call) => {
      if (call.url === '/v1/sessions/') return { sessions: [], next_page_token: null }
      return {}
    })
    setDefaultHttpClient(client)

    render(renderAt('/history', <HistoryPage />))

    await waitFor(() => expect(calls.some((call) => call.url === '/v1/sessions/')).toBe(true))
    await new Promise((resolve) => setTimeout(resolve, 100))

    expect(calls.map(key)).toEqual(['GET /v1/sessions/'])
  })

  it('Session detail cold-loads details and snapshots once', async () => {
    const { calls, client } = makeRecordingClient((call) => {
      if (call.url === '/v1/sessions/7/details') {
        return {
          session_id: 7,
          started_at: '2026-11-01T00:00:00Z',
          ended_at: null,
          start_die: 6,
          current_die: 6,
          ladder_path: '6',
          narrative_summary: {},
          events: [],
        }
      }
      if (call.url === '/v1/sessions/7/snapshots') return { session_id: 7, snapshots: [] }
      return {}
    })
    setDefaultHttpClient(client)

    render(
      renderAt(
        '/sessions/7',
        <Routes>
          <Route path="/sessions/:id" element={<SessionPage />} />
        </Routes>,
      ),
    )

    await waitFor(() => expect(calls.some((call) => call.url === '/v1/sessions/7/snapshots')).toBe(true))
    await new Promise((resolve) => setTimeout(resolve, 100))

    expect(new Set(calls.map(key))).toEqual(
      new Set(['GET /v1/sessions/7/details', 'GET /v1/sessions/7/snapshots']),
    )
  })
})
