/**
 * Issue #4141 — a successful Snooze must own exactly one authoritative
 * `GET /api/v1/roll/bootstrap`. These tests compose the real snooze mutation,
 * the real bootstrap query hook, and each Roll caller (rating view and pool
 * action sheet) so the assertion counts actual API `get` calls instead of a
 * stubbed `refetchBootstrap`. Completion is delayed across a timer turn so the
 * zero-delay `justReconciledRef` window in `useRollBootstrap` has expired and a
 * caller-driven refresh can no longer hide behind it.
 */
import { type ReactNode } from 'react'
import { act, renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'
import type { NavigateFunction } from 'react-router-dom'
import { ToastProvider } from '../contexts/ToastProvider'
import { useSnooze } from '../hooks/useSnooze'
import { useRollBootstrap } from '../hooks/useRollBootstrap'
import { useRollPageState } from '../pages/RollPage/useRollPageState'
import { useRollSnooze } from '../pages/RollPage/useRollSnooze'
import { useRollActions } from '../pages/RollPage/useRollActions'
import { threadsApi } from '../services/api-threads'
import type { RollBootstrapResponse, RollBootstrapThread } from '../types/rollBootstrap'
import type { RatingThread } from '../pages/RollPage/types'

const PENDING_THREAD_ID = 8

function bootstrapState(pendingThreadId: number | null): RollBootstrapResponse {
  return {
    session_id: 1,
    user_id: 1,
    current_die: 12,
    manual_die: null,
    pending_thread_id: pendingThreadId,
    last_rolled_result: pendingThreadId === null ? null : 3,
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
    blocked_count: 0,
    blocked_threads: [],
    skipped_thread_ids: [],
    skipped_threads: [],
    stale_thread_count: 0,
    stale_thread: null,
  }
}

function ratingThread(id: number): RatingThread {
  return {
    id,
    title: `Series ${id}`,
    format: 'Comic',
    issues_remaining: 3,
    queue_position: 1,
    total_issues: 6,
    reading_progress: null,
    issue_id: null,
    issue_number: null,
    next_issue_id: null,
    next_issue_number: null,
    last_rolled_result: null,
  }
}

function pooledThread(id: number): RollBootstrapThread {
  return { id, title: `Series ${id}`, format: 'Comic' }
}

/** Resolve after a macrotask so the reconciliation suppression window expires. */
function afterMacrotask<T>(value: T): Promise<T> {
  return new Promise((resolve) => {
    setTimeout(() => resolve(value), 0)
  })
}

function makeApis() {
  return {
    bootstrapApi: { get: vi.fn(), switchPrerequisite: vi.fn() },
    protectedApi: { rate: vi.fn(), snooze: vi.fn(), skip: vi.fn(), bootstrap: vi.fn() },
    cacheEffects: {
      applyRatedThreadCache: vi.fn(),
      invalidateCurrentSessionAfterSnooze: vi.fn().mockResolvedValue(undefined),
      invalidateAfterSessionModeUpdate: vi.fn(),
    },
  }
}

type Apis = ReturnType<typeof makeApis>

function renderSnoozeFlow(apis: Apis) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <ToastProvider>{children}</ToastProvider>
    </QueryClientProvider>
  )

  const onRefreshFailed = vi.fn()
  const onSnoozeRefreshFailed = vi.fn()

  const rendered = renderHook(() => {
    const state = useRollPageState()
    const bootstrap = useRollBootstrap(apis.bootstrapApi)
    const snoozeMutation = useSnooze(apis)

    const snooze = useRollSnooze({
      state,
      snoozeMutation,
      unsnoozeMutation: { mutate: vi.fn().mockResolvedValue(undefined) },
      refetchBootstrap: bootstrap.refetch,
      onRefreshFailed,
    })

    const actions = useRollActions({
      state,
      bootstrap: bootstrap.data,
      rollPool: bootstrap.data?.roll_pool ?? [],
      // SAFETY: the snooze path never navigates; the stub only satisfies the routing prop.
      navigate: vi.fn() as NavigateFunction,
      mutations: {
        setDieMutation: { mutate: vi.fn().mockResolvedValue(undefined), isPending: false },
        clearManualDieMutation: { mutate: vi.fn().mockResolvedValue(undefined), isPending: false },
        rollMutation: { mutate: vi.fn(), isPending: false },
        snoozeMutation,
        unsnoozeMutation: { mutate: vi.fn().mockResolvedValue(undefined), isPending: false },
        skipMutation: { mutate: vi.fn().mockResolvedValue(undefined), isPending: false },
        unskipMutation: { mutate: vi.fn().mockResolvedValue(undefined), isPending: false },
        moveToFrontMutation: { mutate: vi.fn().mockResolvedValue(undefined), isPending: false },
        moveToBackMutation: { mutate: vi.fn().mockResolvedValue(undefined), isPending: false },
        shuffleQueueMutation: { mutate: vi.fn().mockResolvedValue(undefined), isPending: false },
      },
      refetchBootstrap: bootstrap.refetch,
      enterRatingView: vi.fn().mockResolvedValue(undefined),
      threadsApi,
      onSnoozeRefreshFailed,
    })

    return { state, snooze, actions, bootstrap }
  }, { wrapper })

  return { rendered, onRefreshFailed, onSnoozeRefreshFailed }
}

async function settleInitialBootstrap(
  apis: Apis,
  rendered: { result: { current: { bootstrap: { data: RollBootstrapResponse | null } } } },
): Promise<void> {
  await waitFor(() => expect(apis.bootstrapApi.get).toHaveBeenCalledTimes(1))
  await waitFor(() => expect(rendered.result.current.bootstrap.data).not.toBeNull())
  apis.bootstrapApi.get.mockClear()
}

describe('successful Roll snooze issues one authoritative bootstrap refresh', () => {
  it('rating view: one snooze request and one bootstrap request across a macrotask', async () => {
    const apis = makeApis()
    apis.bootstrapApi.get.mockImplementation(() => afterMacrotask(bootstrapState(null)))
    apis.protectedApi.snooze.mockImplementation(() => afterMacrotask(undefined))
    const { rendered } = renderSnoozeFlow(apis)
    await settleInitialBootstrap(apis, rendered)

    act(() => {
      rendered.result.current.state.setActiveRatingThread(ratingThread(PENDING_THREAD_ID))
      rendered.result.current.state.setIsRatingView(true)
    })

    await act(async () => {
      await rendered.result.current.snooze.handleSnooze()
    })
    await act(async () => {
      await afterMacrotask(null)
    })

    expect(apis.protectedApi.snooze).toHaveBeenCalledTimes(1)
    expect(apis.bootstrapApi.get).toHaveBeenCalledTimes(1)
  })

  it('action sheet: one snooze request and one bootstrap request across a macrotask', async () => {
    const apis = makeApis()
    apis.bootstrapApi.get.mockImplementation(() => afterMacrotask(bootstrapState(PENDING_THREAD_ID)))
    apis.protectedApi.snooze.mockImplementation(() => afterMacrotask(undefined))
    const { rendered } = renderSnoozeFlow(apis)
    await settleInitialBootstrap(apis, rendered)

    act(() => {
      rendered.result.current.state.setSelectedThread(pooledThread(PENDING_THREAD_ID))
    })

    await act(async () => {
      await rendered.result.current.actions.handleAction('snooze')
    })
    await act(async () => {
      await afterMacrotask(null)
    })

    expect(apis.protectedApi.snooze).toHaveBeenCalledTimes(1)
    expect(apis.bootstrapApi.get).toHaveBeenCalledTimes(1)
  })

  it('rating view: an exhausted refresh is reported and never retried by the caller', async () => {
    const apis = makeApis()
    const refreshFailure = new Error('bootstrap unavailable')
    apis.bootstrapApi.get.mockImplementation(() => afterMacrotask(bootstrapState(null)))
    apis.protectedApi.snooze.mockImplementation(() => afterMacrotask(undefined))
    const { rendered, onRefreshFailed } = renderSnoozeFlow(apis)
    await settleInitialBootstrap(apis, rendered)
    apis.bootstrapApi.get.mockImplementation(() => Promise.reject(refreshFailure))

    act(() => {
      rendered.result.current.state.setActiveRatingThread(ratingThread(PENDING_THREAD_ID))
      rendered.result.current.state.setIsRatingView(true)
    })

    await act(async () => {
      await rendered.result.current.snooze.handleSnooze()
    })
    await act(async () => {
      await afterMacrotask(null)
    })

    expect(apis.protectedApi.snooze).toHaveBeenCalledTimes(1)
    // The bounded refresh (two attempts) is the only refresh the snooze owns.
    expect(apis.bootstrapApi.get).toHaveBeenCalledTimes(2)
    expect(onRefreshFailed).toHaveBeenCalledWith(refreshFailure)
  })

  it('action sheet: an exhausted refresh is reported and never retried by the caller', async () => {
    const apis = makeApis()
    const refreshFailure = new Error('bootstrap unavailable')
    apis.bootstrapApi.get.mockImplementation(() => afterMacrotask(bootstrapState(PENDING_THREAD_ID)))
    apis.protectedApi.snooze.mockImplementation(() => afterMacrotask(undefined))
    const { rendered, onSnoozeRefreshFailed } = renderSnoozeFlow(apis)
    await settleInitialBootstrap(apis, rendered)
    apis.bootstrapApi.get.mockImplementation(() => Promise.reject(refreshFailure))

    act(() => {
      rendered.result.current.state.setSelectedThread(pooledThread(PENDING_THREAD_ID))
    })

    await act(async () => {
      await rendered.result.current.actions.handleAction('snooze')
    })
    await act(async () => {
      await afterMacrotask(null)
    })

    expect(apis.protectedApi.snooze).toHaveBeenCalledTimes(1)
    expect(apis.bootstrapApi.get).toHaveBeenCalledTimes(2)
    expect(onSnoozeRefreshFailed).toHaveBeenCalledWith(refreshFailure)
  })
})
