/**
 * Request budgets for the authenticated core views (#4501).
 *
 * Each case mounts the real route component through the real service layer
 * with only the HTTP transport doubled, so the assertions count the exact
 * HTTP method + path + query parameters the browser would send. Exact per-key
 * counts (not `Set`s) make a duplicate in-flight or retry call fail.
 *
 * The shell case records the identity-inbox read at the Axios adapter because
 * that service module still uses the default Axios instance; the other shell
 * read (preferences) goes through the service transport seam.
 */
import { StrictMode, type ReactNode } from 'react'
import { QueryClientProvider, type QueryClient } from '@tanstack/react-query'
import type { InternalAxiosRequestConfig } from 'axios'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { ToastProvider } from '../contexts/ToastProvider'
import { BugReportRestoreProvider } from '../contexts/BugReportRestoreContext'
import { setDefaultHttpClient } from '../services/httpClient'
import { createAppQueryClient } from '../query/queryClient'
import api from '../services/api'
import { AuthContext } from '../contexts/AuthContext'
import { NavCollapseProvider } from '../contexts/NavCollapseContext'
import type { AuthState } from '../services/authState'
import Navigation from '../components/Navigation'
import { PreferencesSync } from '../hooks/usePreferences'
import QueuePage from '../pages/QueuePage'
import RollPage from '../pages/RollPage'
import HistoryPage from '../pages/HistoryPage'
import SessionPage from '../pages/SessionPage'
import {
  createRequestRecorder,
  requestCounts,
  type RecordedCall,
  type Responder,
} from './requestRecorder'

function Providers({ children }: { children: ReactNode }) {
  return (
    <BugReportRestoreProvider>
      <ToastProvider>{children}</ToastProvider>
    </BugReportRestoreProvider>
  )
}

let routeQueryClient: QueryClient

function renderAt(path: string, element: ReactNode, strict = false): ReactNode {
  const tree = (
    <QueryClientProvider client={routeQueryClient}>
      <MemoryRouter initialEntries={[path]}>
        <Providers>{element}</Providers>
      </MemoryRouter>
    </QueryClientProvider>
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
  if (call.url === '/v1/threads/' || call.url === '/v1/threads') {
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

const originalAdapter = api.defaults.adapter
let adapterCalls: RecordedCall[] = []

function installAdapterRecorder(): void {
  api.defaults.adapter = async (config: InternalAxiosRequestConfig) => {
    adapterCalls.push({
      method: (config.method ?? 'get').toUpperCase(),
      url: config.url ?? '',
      // SAFETY: the identity service always sends offset/limit search params.
      params: config.params as Record<string, string | number>,
    })
    return {
      status: 200,
      statusText: 'OK',
      headers: {},
      config,
      data: { items: [], total: 0, offset: 0, limit: 1 },
    }
  }
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

beforeEach(() => {
  adapterCalls = []
  // A per-test client keeps these budgets independent of the process-wide
  // singleton that other unit files populate.
  routeQueryClient = createAppQueryClient()
  const defaults = routeQueryClient.getDefaultOptions()
  routeQueryClient.setDefaultOptions({
    queries: { ...(defaults.queries ?? {}), retry: false },
    mutations: { ...(defaults.mutations ?? {}), retry: false },
  })
})

afterEach(() => {
  api.defaults.adapter = originalAdapter
})

describe('core route request budgets', () => {
  it('authenticated shell cold-loads preferences and inbox status exactly once each', async () => {
    installAdapterRecorder()
    const { calls, client } = createRequestRecorder((call) => {
      if (call.url === '/v1/users/me/preferences') return { theme: 'classic', user_id: 1 }
      return {}
    })
    setDefaultHttpClient(client)

    render(renderShell())

    await waitFor(() =>
      expect(calls.some((call) => call.url === '/v1/users/me/preferences')).toBe(true),
    )
    await waitFor(() => expect(adapterCalls.length).toBeGreaterThan(0))
    await new Promise((resolve) => setTimeout(resolve, 100))

    expect(requestCounts(calls)).toEqual({
      'GET /v1/users/me/preferences': 1,
    })
    expect(requestCounts(adapterCalls)).toEqual({
      'GET /v1/identity-inbox?limit=1&offset=0': 1,
    })
  })

  it('Roll cold-loads one bootstrap read, even under StrictMode', async () => {
    const { calls, client } = createRequestRecorder((call) => {
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
    const { calls, client } = createRequestRecorder(queueHandler)
    setDefaultHttpClient(client)

    const view = render(renderAt('/queue', <QueuePage />))

    await waitFor(() =>
      expect(calls.some((call) => call.url === '/v1/threads:getBlockingInfo')).toBe(true),
    )
    await new Promise((resolve) => setTimeout(resolve, 100))

    expect(requestCounts(calls)).toEqual({
      'GET /v1/threads/?page_size=50&sort=position': 1,
      'GET /v1/sessions/current/': 1,
      'GET /v1/threads/excluded/threads?page_size=50&sort=created': 1,
      'POST /v2/reading-boundaries': 1,
      'POST /v1/threads/groups:batch': 1,
      'POST /v1/threads:getBlockingInfo': 1,
    })

    view.unmount()
    const warmed = calls.length
    render(renderAt('/queue', <QueuePage />))
    await new Promise((resolve) => setTimeout(resolve, 100))
    expect(calls).toHaveLength(warmed)
  })

  it('Queue search commits one request for the final debounced value', async () => {
    const { calls, client } = createRequestRecorder(queueHandler)
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
    const { calls, client } = createRequestRecorder((call) => {
      if (call.url === '/v1/sessions/') return { sessions: [], next_page_token: null }
      return {}
    })
    setDefaultHttpClient(client)

    render(renderAt('/history', <HistoryPage />))

    await waitFor(() => expect(calls.some((call) => call.url === '/v1/sessions/')).toBe(true))
    await new Promise((resolve) => setTimeout(resolve, 100))

    expect(requestCounts(calls)).toEqual({ 'GET /v1/sessions/': 1 })
  })

  it('Session detail cold-loads details and snapshots exactly once', async () => {
    const { calls, client } = createRequestRecorder((call) => {
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

    await waitFor(() =>
      expect(calls.some((call) => call.url === '/v1/sessions/7/snapshots')).toBe(true),
    )
    await new Promise((resolve) => setTimeout(resolve, 100))

    expect(requestCounts(calls)).toEqual({
      'GET /v1/sessions/7/details': 1,
      'GET /v1/sessions/7/snapshots': 1,
    })
  })
})
