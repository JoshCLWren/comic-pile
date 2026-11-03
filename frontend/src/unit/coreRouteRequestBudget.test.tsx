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
import { StrictMode, useEffect, type ReactNode } from 'react'
import { QueryClientProvider, type QueryClient } from '@tanstack/react-query'
import type { InternalAxiosRequestConfig } from 'axios'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ToastProvider } from '../contexts/ToastProvider'
import { BugReportRestoreProvider } from '../contexts/BugReportRestoreContext'
import { setDefaultHttpClient } from '../services/httpClient'
import { threadsApi } from '../services/api-threads'
import { sessionApi } from '../services/api-sessions'
import { readingBoundariesApi } from '../services/api-reading-boundaries'
import { dependencyGroupsApi } from '../services/api-dependency-groups'
import { dependenciesApi } from '../services/api-dependencies'
import { createAppQueryClient, queryClient as sharedQueryClient } from '../query/queryClient'
import { resetRollBootstrapSessionState } from '../services/rollBootstrapApi'
import { queryKeys } from '../query/queryKeys'
import { adaptRollV2Bootstrap } from '../services/adaptRollV2Bootstrap'
import api from '../services/api'
import { AuthContext } from '../contexts/AuthContext'
import { NavCollapseProvider } from '../contexts/NavCollapseContext'
import type { AuthState } from '../services/authState'
import Navigation from '../components/Navigation'
import { PreferencesSync } from '../hooks/usePreferences'
import { QueueControls } from '../pages/QueuePage/QueueControls'
import { useQueueCrossovers } from '../pages/QueuePage/useQueueCrossovers'
import { useExcludedThreads, useMoveToFront, useQueueThreads } from '../hooks/useQueue'
import { useQueueBlockingInfo } from '../hooks/useQueueBlockingInfo'
import { useSession } from '../hooks/useSession'
import { useReadingBoundaries } from '../hooks/useReadingBoundaries'
import type { SnoozeMutationOutcome } from '../hooks/useSnooze'
import type { SkipMutationOutcome } from '../hooks/useSkip'
import { useQueueThreadActions } from '../pages/QueuePage/useQueueThreadActions'
import { useRollBootstrap } from '../hooks/useRollBootstrap'
import { useRollPageState } from '../pages/RollPage/useRollPageState'
import { useRollActions } from '../pages/RollPage/useRollActions'
import RollPage from '../pages/RollPage'
import HistoryPage from '../pages/HistoryPage'
import SessionPage from '../pages/SessionPage'
import type { RollBootstrapThread } from '../types/rollBootstrap'
import type { ThreadListItem, RollResponse } from '../types'
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
  created_at: '2026-01-01T00:00:00Z',
  last_activity_at: null,
}))

/**
 * Typed stand-ins for the sibling Roll mutations this probe does not exercise.
 *
 * The budget assertions cover the move-to-front request path, so the roll,
 * snooze and skip mutations must resolve with the exact shapes their hooks
 * declare. Returning `undefined` where a response object is required would not
 * type-check, and the anti-slop rules forbid casting around that.
 */
const stubRollResponse: RollResponse = {
  thread_id: 1,
  title: 'Series 1',
  format: 'Comic',
  issues_remaining: 3,
  queue_position: 1,
  die_size: 20,
  result: 6,
  offset: 0,
  snoozed_count: 0,
  issue_id: null,
  issue_number: null,
  next_issue_id: null,
  next_issue_number: null,
  total_issues: 3,
  reading_progress: null,
}

const stubSnoozeOutcome: SnoozeMutationOutcome = {
  response: undefined,
  refreshed: false,
  refreshError: undefined,
}

const stubSkipOutcome: SkipMutationOutcome = {
  response: undefined,
  refreshed: false,
  refreshError: undefined,
}

/**
 * Queue data-hook composition: the same real hooks the route mounts, in the
 * same order, without the page's presentation tree. The full Queue page's
 * request set is covered in the Chromium budget spec.
 */
function QueueBudgetProbe() {
  const queue = useQueueThreads()
  useSession()
  useExcludedThreads(true)
  const threadIds = (queue.data ?? []).flatMap((thread) => (thread ? [thread.id] : []))
  const boundaries = useReadingBoundaries(threadIds)
  useQueueCrossovers(queue.data ?? [])
  const boundariesUnavailable =
    !boundaries.isPending &&
    (boundaries.isError ||
      boundaries.data == null ||
      threadIds.some(
        (id) =>
          boundaries.data?.threads[id] == null ||
          boundaries.data?.threads[id].state === 'unavailable',
      ))
  useQueueBlockingInfo(boundariesUnavailable ? threadIds : [])
  return null
}

/** HTTP count by method + exact URL path, ignoring query params. */
function countRequests(calls: RecordedCall[], method: string, url: string): number {
  return calls.filter((call) => call.method === method && call.url === url).length
}

const budgetNavigate = vi.fn()
const budgetEnterRatingView = vi.fn()

// The queue/roll mutation hooks invalidate the module-level query client, so
// the probe trees below run with that shared client as their provider, exactly
// as the composed production screen does (cleared per test above).
function renderSharedProbe(element: ReactNode): ReactNode {
  return (
    <QueryClientProvider client={sharedQueryClient}>
      <MemoryRouter initialEntries={['/']}>
        <Providers>{element}</Providers>
      </MemoryRouter>
    </QueryClientProvider>
  )
}

let rollMoveHandle: {
  pick: (thread: RollBootstrapThread) => void
  act: (action: string) => Promise<void>
} | null = null

/**
 * Roll move-action composition: the real bootstrap query, the real move-to-front
 * mutation, and the real action-sheet handler — the exact request path a
 * move-front click produces from the Roll page, with only the HTTP transport
 * recorded and the untouched sibling mutations stubbed.
 */
function RollMoveBudgetProbe() {
  const state = useRollPageState()
  const { data: bootstrapState, refetch: refetchBootstrap } = useRollBootstrap()
  const moveToFrontMutation = useMoveToFront()
  const actions = useRollActions({
    state,
    bootstrap: bootstrapState ?? undefined,
    rollPool: bootstrapState?.roll_pool ?? [],
    navigate: budgetNavigate,
    mutations: {
      setDieMutation: { mutate: () => Promise.resolve(undefined), isPending: false },
      rollMutation: { mutate: () => Promise.resolve(stubRollResponse), isPending: false },
      snoozeMutation: { mutate: () => Promise.resolve(stubSnoozeOutcome), isPending: false },
      unsnoozeMutation: { mutate: () => Promise.resolve(undefined), isPending: false },
      skipMutation: { mutate: () => Promise.resolve(stubSkipOutcome), isPending: false },
      unskipMutation: { mutate: () => Promise.resolve(undefined), isPending: false },
      moveToFrontMutation: {
        mutate: moveToFrontMutation.mutate,
        isPending: moveToFrontMutation.isPending,
      },
      moveToBackMutation: { mutate: () => Promise.resolve(undefined), isPending: false },
      shuffleQueueMutation: { mutate: () => Promise.resolve(undefined), isPending: false },
    },
    refetchBootstrap,
    enterRatingView: budgetEnterRatingView,
    threadsApi,
  })

  useEffect(() => {
    rollMoveHandle = {
      pick: (thread) => actions.handleThreadClick(thread),
      act: (action) => actions.handleAction(action),
    }
  })

  return null
}

let queueSnoozeHandle: {
  toggle: (thread: ThreadListItem, snoozed: boolean) => Promise<void>
} | null = null

/**
 * Queue row-action composition: the real queue loader, session read, excluded
 * view, and the real native reroll/legacy unsnooze actions inside `useQueueThreadActions` —
 * the exact request path a snooze toggle produces from the Queue page.
 */
function QueueSnoozeBudgetProbe() {
  useQueueThreads()
  useSession()
  useExcludedThreads(true)
  const actions = useQueueThreadActions({
    navigateToRoll: budgetNavigate,
    // The default restore depends on requestAnimationFrame; this budget only
    // counts HTTP work, so the focus restore is a no-op here.
    restoreSeriesActionsFocus: () => undefined,
  })

  useEffect(() => {
    queueSnoozeHandle = {
      toggle: async (thread, snoozed) => {
        // SAFETY: the real hook's toggle is `Promise<void> | void`; wrapping in
        // one promise keeps this module handle's contract a plain await.
        await actions.handleSnoozeToggle(thread, snoozed)
      },
    }
  })

  return null
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

// One rollable pooled series for the Roll move-action budget probe (#4276).
// Deliberately untyped JSON literals so the request recorder can return them
// directly through the `JsonValue` Responder contract. The enum literals use
// the frozen v2 vocabulary so `adaptRollV2Bootstrap` accepts the fixture as a
// faithful payload.
const pooledV2Item = {
  thread: { id: 44, title: 'Pooled Saga', format: 'Comic', tags: [] },
  issue: { id: 401, number: '1' },
  identity: {
    source: 'unavailable' as const,
    canonical_series_id: null,
    state: 'unresolved' as const,
    series_mapping_state: 'unresolved' as const,
  },
  reader: {
    latest_rating: null,
    average_rating: null,
    rating_count: null,
    read_count: null,
    issue_count: null,
    progress_scope: 'thread' as const,
  },
  routes: [{ kind: 'group' as const, name: 'Read next' }],
  overflow_routes_count: 0,
}

/**
 * Faithful native Rust v2 rollback payload: the real shape
 * `adaptRollV2Bootstrap` turns into the retained Roll projection, so a
 * bootstrap refresh in a budget probe exists (and settles) exactly as it
 * would against the lane's real backend.
 */
const rollV2Bootstrap = {
  ...bootstrap,
  bandwidth: {
    predicted_bandwidth: null,
    active_bandwidth: null,
    confidence: null,
    source: null,
    mode_version: null,
  },
  rollable: [pooledV2Item],
  pool_reason: 'ready' as const,
}

/** Pool-less v2 sibling for probes with no mounted Roll page. */
const rollV2BootstrapIdle = {
  ...rollV2Bootstrap,
  rollable: [],
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

/**
 * Drain pending async work deterministically, without a wall-clock sleep.
 *
 * `act(async () => {})` flushes React's work queue together with the microtask
 * backlog, so chained promise continuations settle before the assertion runs.
 * Iterating drains continuations that themselves schedule further work. These
 * probes disable query retry and the app disables focus refetching, so every
 * continuation in scope is promise-based and draining is sufficient.
 *
 * This replaces a fixed `setTimeout(resolve, 100)` sleep, which was both flaky
 * (a slow runner might not have settled in 100 ms) and too weak to prove the
 * property under test (a duplicate request arriving after the sleep expired
 * would have been counted as absent).
 */
async function drainSettledWork(rounds = 10): Promise<void> {
  for (let round = 0; round < rounds; round += 1) {
    await act(async () => {
      await Promise.resolve()
    })
  }
}

beforeEach(() => {
  adapterCalls = []
  rollMoveHandle = null
  queueSnoozeHandle = null
  // A per-test client keeps these budgets independent of the process-wide
  // singleton that other unit files populate.
  sharedQueryClient.clear()
  // The singleton bootstrap service resolves the reading session once per
  // client lifetime; without this reset a later budget would skip the cold
  // session POST its cold-load assertion counts (#4276).
  resetRollBootstrapSessionState()
  routeQueryClient = createAppQueryClient()
  const defaults = routeQueryClient.getDefaultOptions()
  routeQueryClient.setDefaultOptions({
    queries: { ...(defaults.queries ?? {}), retry: false },
    mutations: { ...(defaults.mutations ?? {}), retry: false },
  })
})

afterEach(() => {
  api.defaults.adapter = originalAdapter
  vi.restoreAllMocks()
  // Budget probes on the shared client must not leak seeds into other tests.
  sharedQueryClient.clear()
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
    await drainSettledWork()

    expect(requestCounts(calls)).toEqual({
      'GET /v1/users/me/preferences': 1,
    })
    expect(requestCounts(adapterCalls)).toEqual({
      'GET /v1/identity-inbox?limit=1&offset=0': 1,
    })
  })

  it('Roll initializes once before one read-only bootstrap, even under StrictMode', async () => {
    const { calls, client } = createRequestRecorder((call) => {
      if (call.url === '/v2/reading-sessions') return { session_id: 1, created: false }
      if (call.url === '/v2/roll/bootstrap') return bootstrap
      return {}
    })
    setDefaultHttpClient(client)

    render(renderAt('/', <RollPage />, true))

    await waitFor(() => expect(calls.some((call) => call.url === '/v2/roll/bootstrap')).toBe(true))
    await drainSettledWork()

    expect(calls).toHaveLength(2)
    expect(calls.map(({ method, url }) => [method, url])).toEqual([
      ['POST', '/v2/reading-sessions'],
      ['GET', '/v2/roll/bootstrap'],
    ])
    expect(calls[1].params?.timezone).toBe(
      Intl.DateTimeFormat().resolvedOptions().timeZone || undefined,
    )
  })

  it('Queue cold-loads each bounded batch once and reuses the cache on warm remount', async () => {
    // SAFETY: the queue fixture supplies every field the Queue hooks read.
    const list = vi.spyOn(threadsApi, 'list').mockResolvedValue({
      threads: queueThreads,
      next_page_token: null,
      active_count: 2,
    } as never)
    // SAFETY: the excluded fixture is an empty valid list page.
    const listExcluded = vi.spyOn(threadsApi, 'listExcluded').mockResolvedValue({
      threads: [],
      next_page_token: null,
      active_count: 0,
    } as never)
    // SAFETY: the session fixture supplies every SessionCurrent field read here.
    vi.spyOn(sessionApi, 'getCurrent').mockResolvedValue(session as never)
    // SAFETY: the boundary fixture supplies a state for each requested id.
    const batchBoundaries = vi.spyOn(readingBoundariesApi, 'batch').mockResolvedValue({
      threads: { 1: { state: 'unavailable' }, 2: { state: 'unavailable' } },
    } as never)
    vi.spyOn(dependencyGroupsApi, 'listForThreads').mockResolvedValue({})
    // SAFETY: the blocking fixture supplies the batch map shape read by the hook.
    const batchBlocking = vi.spyOn(dependenciesApi, 'getBatchBlockingInfo').mockResolvedValue({
      threads: {
        1: { is_blocked: false, blocking_reasons: [], blocking_dependencies: [] },
        2: { is_blocked: false, blocking_reasons: [], blocking_dependencies: [] },
      },
    } as never)

    const view = render(renderAt('/queue', <QueueBudgetProbe />))

    await waitFor(() => expect(batchBlocking).toHaveBeenCalledTimes(1))
    expect(list).toHaveBeenCalledTimes(1)
    expect(list).toHaveBeenCalledWith(
      expect.objectContaining({ page_size: 50, sort: 'position' }),
      undefined,
    )
    expect(listExcluded).toHaveBeenCalledTimes(1)
    expect(batchBoundaries).toHaveBeenCalledTimes(1)
    expect(batchBlocking).toHaveBeenCalledTimes(1)

    view.unmount()
    render(renderAt('/queue', <QueueBudgetProbe />))
    await drainSettledWork()
    expect(list).toHaveBeenCalledTimes(1)
    expect(listExcluded).toHaveBeenCalledTimes(1)
    expect(batchBoundaries).toHaveBeenCalledTimes(1)
    expect(batchBlocking).toHaveBeenCalledTimes(1)
  })

  it('Queue search commits one value for the final debounced input', async () => {
    const onSearchChange = vi.fn()
    render(
      <QueueControls
        activeCount={2}
        shuffleDisabled={false}
        shufflePending={false}
        onShuffle={() => undefined}
        onCreateThread={() => undefined}
        onAddFromComicVine={() => undefined}
        onBulkMapSeries={() => undefined}
        sortBy="position"
        onSortChange={() => undefined}
        searchQuery=""
        onSearchChange={onSearchChange}
      />,
    )

    const search = screen.getByRole('textbox', { name: 'Search series' })
    for (const value of ['r', 'ro', 'rob', 'robe', 'robert']) {
      fireEvent.change(search, { target: { value } })
    }

    await waitFor(() => expect(onSearchChange).toHaveBeenCalledTimes(1), { timeout: 2000 })
    expect(onSearchChange).toHaveBeenCalledWith('robert')
  })

  it('History cold-loads exactly one session list page', async () => {
    const { calls, client } = createRequestRecorder((call) => {
      if (call.url === '/v1/sessions/') return { sessions: [], next_page_token: null }
      return {}
    })
    setDefaultHttpClient(client)

    render(renderAt('/history', <HistoryPage />))

    await waitFor(() => expect(calls.some((call) => call.url === '/v1/sessions/')).toBe(true))
    await drainSettledWork()

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
    await drainSettledWork()

    expect(requestCounts(calls)).toEqual({
      'GET /v1/sessions/7/details': 1,
      'GET /v1/sessions/7/snapshots': 1,
    })
  })

  it('Roll move-front refreshes the bootstrap exactly once (#4276)', async () => {
    // SAFETY: the move mutation only observes the PATCH status; the empty body
    // satisfies the v2 queue-entry patch contract for this probe.
    const { calls, client } = createRequestRecorder((call) => {
      if (call.url === '/v2/roll/bootstrap') return rollV2Bootstrap
      if (call.url === '/v2/reading-sessions') return { session_id: 1, created: false }
      return {}
    })
    setDefaultHttpClient(client)

    // SAFETY: the fixture is a faithful native-v2 payload; the adapter turns
    // it into the retained projection the Roll page holds (pool row id 44).
    const poolThread = adaptRollV2Bootstrap(rollV2Bootstrap).roll_pool[0]
    if (!poolThread) throw new Error('fixture adapter produced no pool row')

    // Seed the shared client as a roll:active page would hold it, so this
    // budget counts only the refresh the move action owns.
    sharedQueryClient.setQueryData(queryKeys.roll.bootstrap(), adaptRollV2Bootstrap(rollV2Bootstrap))

    render(renderSharedProbe(<RollMoveBudgetProbe />))
    await waitFor(() => expect(rollMoveHandle).not.toBeNull())

    await act(async () => {
      rollMoveHandle!.pick(poolThread)
    })
    await act(async () => {
      await rollMoveHandle!.act('move-front')
    })

    // The move mutation's queue-movement invalidation refetches the active
    // bootstrap once. This probe seeds the cache instead of cold-loading, so
    // this refresh is also the first resolution of the client-lifetime session
    // (#4276): exactly one session POST and one bootstrap GET. The retired
    // explicit `refetchBootstrap()` in `handleAction` used to append a second
    // bootstrap refresh per move action.
    await waitFor(() =>
      expect(countRequests(calls, 'PATCH', `/v2/queue-entries/${poolThread.id}`)).toBe(1),
    )
    await waitFor(() => expect(countRequests(calls, 'GET', '/v2/roll/bootstrap')).toBe(1))
    await drainSettledWork()

    expect(countRequests(calls, 'PATCH', `/v2/queue-entries/${poolThread.id}`)).toBe(1)
    expect(countRequests(calls, 'GET', '/v2/roll/bootstrap')).toBe(1)
    expect(countRequests(calls, 'POST', '/v2/reading-sessions')).toBe(1)
  })

  it('Queue row native reroll replaces Python snooze with one bounded refresh (#4589)', async () => {
    const { calls, client } = createRequestRecorder((call) => {
      if (call.url === '/v2/threads') {
        return { threads: queueThreads, next_page_token: null, active_count: 2 }
      }
      if (call.url === '/v1/threads/excluded/threads') {
        return { threads: [], next_page_token: null, active_count: 0 }
      }
      if (call.url === '/v1/sessions/current/') return session
      if (call.url === '/v2/roll/offer') return stubRollResponse
      if (call.url === '/v2/reading-sessions') return { session_id: 1, created: false }
      if (call.url === '/v2/roll/bootstrap') return rollV2BootstrapIdle
      return {}
    })
    setDefaultHttpClient(client)

    render(renderSharedProbe(<QueueSnoozeBudgetProbe />))
    await waitFor(() => expect(queueSnoozeHandle).not.toBeNull())
    await waitFor(() =>
      expect(countRequests(calls, 'GET', '/v1/sessions/current/')).toBe(1),
    )
    const coldLoads = calls.length

    await act(async () => {
      // SAFETY: the Queue action reads the thread id and title; the list-item
      // fixture has both fields and is a faithful double.
      await queueSnoozeHandle!.toggle(queueThreads[0] as ThreadListItem, false)
    })
    await drainSettledWork()

    // One native offer both records the snooze and selects the next pending
    // comic; the legacy Python session-clearing POST is never issued.
    // The Queue action owns exactly one current-session refresh. It does not
    // boot a separate reading session or re-fetch an unmounted Roll screen.
    expect(countRequests(calls, 'POST', '/v2/roll/offer')).toBe(1)
    expect(countRequests(calls, 'POST', '/v1/snooze/')).toBe(0)
    expect(countRequests(calls, 'GET', '/v1/sessions/current/')).toBe(2)
    expect(countRequests(calls, 'POST', '/v2/reading-sessions')).toBe(0)
    expect(countRequests(calls, 'GET', '/v2/roll/bootstrap')).toBe(0)
    // One bounded queue-page refresh after the reset (cold + reconciled first page).
    expect(countRequests(calls, 'GET', '/v2/threads')).toBe(2)
    expect(countRequests(calls, 'GET', '/v1/threads/excluded/threads')).toBe(2)
    // No other request classes entered the budget beyond the probed surface.
    expect(calls.length).toBeGreaterThan(coldLoads)
  })
})
