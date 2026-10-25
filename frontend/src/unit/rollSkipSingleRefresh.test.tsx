/**
 * Issue #4142 — a successful Skip must own exactly one authoritative
 * `GET /api/v1/roll/bootstrap`. These tests compose the real skip mutation,
 * the real bootstrap query hook, and each Roll caller (rating view and pool
 * action sheet) so the assertion counts actual API `get` calls instead of a
 * stubbed `refetchBootstrap`. Completion is delayed across a timer turn so the
 * zero-delay `justReconciledRef` window in `useRollBootstrap` has expired and a
 * caller-driven refresh can no longer hide behind it.
 */
import { type ReactNode } from 'react'
import { act, renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { NavigateFunction } from 'react-router-dom'
import { ToastProvider } from '../contexts/ToastProvider'
import { useSkip, useUnskip } from '../hooks/useSkip'
import { useRollBootstrap } from '../hooks/useRollBootstrap'
import { useRollPageState } from '../pages/RollPage/useRollPageState'
import { useRollSkip } from '../pages/RollPage/useRollSkip'
import { useRollActions } from '../pages/RollPage/useRollActions'
import { threadsApi } from '../services/api-threads'
import type { RollResponse } from '../types'
import type { RollBootstrapResponse, RollBootstrapThread } from '../types/rollBootstrap'

const PENDING_THREAD_ID = 8

function bootstrapState(
  pendingThreadId: number | null,
  skippedThreadIds: number[] = [],
): RollBootstrapResponse {
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
    skipped_thread_ids: skippedThreadIds,
    skipped_threads: skippedThreadIds.map((id) => ({
      id,
      title: `Series ${id}`,
      format: 'Comic',
    })),
    stale_thread_count: 0,
    stale_thread: null,
  }
}

function skipResponse(id: number): RollResponse {
  return {
    thread_id: id,
    title: `Series ${id}`,
    format: 'Comic',
    issues_remaining: 3,
    queue_position: 1,
    die_size: 12,
    result: 4,
    offset: 0,
    snoozed_count: 0,
    issue_id: 20,
    issue_number: '7',
    next_issue_id: 21,
    next_issue_number: '8',
    total_issues: 12,
    reading_progress: '50',
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
    skipApi: { skip: vi.fn(), unskip: vi.fn() },
    cacheEffects: {
      applyRatedThreadCache: vi.fn(),
      invalidateCurrentSessionAfterSnooze: vi.fn().mockResolvedValue(undefined),
      invalidateAfterSessionModeUpdate: vi.fn(),
    },
  }
}

type Apis = ReturnType<typeof makeApis>

function makeWrapper() {
  // The unit setup already wraps every render in the app's shared query client,
  // so published bootstrap state reaches the hook this test reads.
  return ({ children }: { children: ReactNode }) => (
    <ToastProvider>{children}</ToastProvider>
  )
}

function renderRatingSkipFlow(apis: Apis) {
  const wrapper = makeWrapper()
  const onRefreshFailed = vi.fn()
  const enterRatingView = vi.fn().mockResolvedValue(undefined)

  const rendered = renderHook(() => {
    const state = useRollPageState()
    const bootstrap = useRollBootstrap(apis.bootstrapApi)
    const skipMutation = useSkip(apis)
    const unskipMutation = useUnskip(apis)

    const skip = useRollSkip({
      state,
      skipMutation,
      unskipMutation,
      refetchBootstrap: bootstrap.refetch,
      enterRatingView,
      expectedPendingThreadId: bootstrap.data?.pending_thread_id ?? undefined,
      onRefreshFailed,
    })

    return { state, skip, bootstrap }
  }, { wrapper })

  return { rendered, onRefreshFailed, enterRatingView }
}

function renderActionSheetFlow(apis: Apis) {
  const wrapper = makeWrapper()
  const onSkipRefreshFailed = vi.fn()

  const rendered = renderHook(() => {
    const state = useRollPageState()
    const bootstrap = useRollBootstrap(apis.bootstrapApi)
    const skipMutation = useSkip(apis)
    const unskipMutation = useUnskip(apis)

    const actions = useRollActions({
      state,
      bootstrap: bootstrap.data,
      rollPool: bootstrap.data?.roll_pool ?? [],
      // SAFETY: the skip path never navigates; the stub only satisfies the routing prop.
      navigate: vi.fn() as NavigateFunction,
      mutations: {
        setDieMutation: { mutate: vi.fn().mockResolvedValue(undefined), isPending: false },
        clearManualDieMutation: { mutate: vi.fn().mockResolvedValue(undefined), isPending: false },
        rollMutation: { mutate: vi.fn(), isPending: false },
        snoozeMutation: { mutate: vi.fn().mockResolvedValue({ refreshed: true, refreshError: null }), isPending: false },
        unsnoozeMutation: { mutate: vi.fn().mockResolvedValue(undefined), isPending: false },
        skipMutation,
        unskipMutation,
        moveToFrontMutation: { mutate: vi.fn().mockResolvedValue(undefined), isPending: false },
        moveToBackMutation: { mutate: vi.fn().mockResolvedValue(undefined), isPending: false },
        shuffleQueueMutation: { mutate: vi.fn().mockResolvedValue(undefined), isPending: false },
      },
      refetchBootstrap: bootstrap.refetch,
      enterRatingView: vi.fn().mockResolvedValue(undefined),
      threadsApi,
      onSkipRefreshFailed,
    })

    return { state, actions, bootstrap }
  }, { wrapper })

  return { rendered, onSkipRefreshFailed }
}

async function settleInitialBootstrap(
  apis: Apis,
  rendered: { result: { current: { bootstrap: { data: RollBootstrapResponse | null } } } },
): Promise<void> {
  await waitFor(() => expect(apis.bootstrapApi.get).toHaveBeenCalledTimes(1))
  await waitFor(() => expect(rendered.result.current.bootstrap.data).not.toBeNull())
  apis.bootstrapApi.get.mockClear()
}

describe('successful Roll skip issues one authoritative bootstrap refresh', () => {
  it('rating view: one skip request and one bootstrap request across a macrotask', async () => {
    const apis = makeApis()
    apis.bootstrapApi.get.mockImplementation(() => afterMacrotask(bootstrapState(PENDING_THREAD_ID)))
    apis.protectedApi.skip.mockImplementation(() => afterMacrotask(skipResponse(PENDING_THREAD_ID)))
    const { rendered, enterRatingView } = renderRatingSkipFlow(apis)
    await settleInitialBootstrap(apis, rendered)
    apis.bootstrapApi.get.mockImplementation(() => afterMacrotask(bootstrapState(null)))

    act(() => {
      rendered.result.current.state.setIsRatingView(true)
    })

    await act(async () => {
      await rendered.result.current.skip.handleSkip()
    })
    await act(async () => {
      await afterMacrotask(null)
    })

    expect(apis.protectedApi.skip).toHaveBeenCalledTimes(1)
    expect(apis.bootstrapApi.get).toHaveBeenCalledTimes(1)
    expect(enterRatingView).toHaveBeenCalledWith(
      PENDING_THREAD_ID,
      4,
      expect.objectContaining({ id: PENDING_THREAD_ID, title: `Series ${PENDING_THREAD_ID}` }),
    )
    expect(rendered.result.current.state.rolledResult).toBe(4)
    // The published snapshot already reflects the consumed pending read.
    expect(rendered.result.current.bootstrap.data?.pending_thread_id).toBeNull()
  })

  it('action sheet: one skip request and one bootstrap request across a macrotask', async () => {
    const apis = makeApis()
    apis.bootstrapApi.get.mockImplementation(() => afterMacrotask(bootstrapState(PENDING_THREAD_ID)))
    apis.protectedApi.skip.mockImplementation(() => afterMacrotask(skipResponse(PENDING_THREAD_ID)))
    const { rendered } = renderActionSheetFlow(apis)
    await settleInitialBootstrap(apis, rendered)

    act(() => {
      rendered.result.current.state.setSelectedThread(pooledThread(PENDING_THREAD_ID))
    })

    await act(async () => {
      await rendered.result.current.actions.handleAction('skip')
    })
    await act(async () => {
      await afterMacrotask(null)
    })

    expect(apis.protectedApi.skip).toHaveBeenCalledTimes(1)
    expect(apis.bootstrapApi.get).toHaveBeenCalledTimes(1)
  })

  it('rating view: an exhausted refresh is reported without a caller retry', async () => {
    const apis = makeApis()
    const refreshFailure = new Error('bootstrap unavailable')
    apis.bootstrapApi.get.mockImplementation(() => afterMacrotask(bootstrapState(PENDING_THREAD_ID)))
    apis.protectedApi.skip.mockImplementation(() => afterMacrotask(skipResponse(PENDING_THREAD_ID)))
    const { rendered, onRefreshFailed, enterRatingView } = renderRatingSkipFlow(apis)
    await settleInitialBootstrap(apis, rendered)
    apis.bootstrapApi.get.mockImplementation(() => Promise.reject(refreshFailure))

    act(() => {
      rendered.result.current.state.setIsRatingView(true)
    })

    await act(async () => {
      await rendered.result.current.skip.handleSkip()
    })
    await act(async () => {
      await afterMacrotask(null)
    })

    expect(apis.protectedApi.skip).toHaveBeenCalledTimes(1)
    // The bounded refresh (two attempts) is the only refresh the skip owns.
    expect(apis.bootstrapApi.get).toHaveBeenCalledTimes(2)
    expect(onRefreshFailed).toHaveBeenCalledWith(refreshFailure)
    // The committed skip still advances the rating view from its response.
    expect(enterRatingView).toHaveBeenCalledTimes(1)
  })

  it('action sheet: an exhausted refresh is reported without a caller retry', async () => {
    const apis = makeApis()
    const refreshFailure = new Error('bootstrap unavailable')
    apis.bootstrapApi.get.mockImplementation(() => afterMacrotask(bootstrapState(PENDING_THREAD_ID)))
    apis.protectedApi.skip.mockImplementation(() => afterMacrotask(skipResponse(PENDING_THREAD_ID)))
    const { rendered, onSkipRefreshFailed } = renderActionSheetFlow(apis)
    await settleInitialBootstrap(apis, rendered)
    apis.bootstrapApi.get.mockImplementation(() => Promise.reject(refreshFailure))

    act(() => {
      rendered.result.current.state.setSelectedThread(pooledThread(PENDING_THREAD_ID))
    })

    await act(async () => {
      await rendered.result.current.actions.handleAction('skip')
    })
    await act(async () => {
      await afterMacrotask(null)
    })

    expect(apis.protectedApi.skip).toHaveBeenCalledTimes(1)
    expect(apis.bootstrapApi.get).toHaveBeenCalledTimes(2)
    expect(onSkipRefreshFailed).toHaveBeenCalledWith(refreshFailure)
  })

  it('unskip from the rating view refreshes once and drops skipped membership', async () => {
    const apis = makeApis()
    apis.bootstrapApi.get.mockImplementation(() => afterMacrotask(bootstrapState(PENDING_THREAD_ID, [PENDING_THREAD_ID])))
    apis.skipApi.unskip.mockResolvedValue(undefined)
    const { rendered } = renderRatingSkipFlow(apis)
    await settleInitialBootstrap(apis, rendered)

    apis.bootstrapApi.get.mockImplementation(() => afterMacrotask(bootstrapState(PENDING_THREAD_ID, [])))
    await act(async () => {
      await rendered.result.current.skip.handleUnskip(PENDING_THREAD_ID)
    })

    expect(apis.skipApi.unskip).toHaveBeenCalledWith(PENDING_THREAD_ID)
    expect(apis.bootstrapApi.get).toHaveBeenCalledTimes(1)
    await waitFor(() => {
      expect(rendered.result.current.bootstrap.data?.skipped_thread_ids).toEqual([])
    })
  })

  it('unskip from the action sheet refreshes once and drops skipped membership', async () => {
    const apis = makeApis()
    apis.bootstrapApi.get.mockImplementation(() => afterMacrotask(bootstrapState(PENDING_THREAD_ID, [PENDING_THREAD_ID])))
    apis.skipApi.unskip.mockResolvedValue(undefined)
    const { rendered } = renderActionSheetFlow(apis)
    await settleInitialBootstrap(apis, rendered)

    act(() => {
      rendered.result.current.state.setSelectedThread(pooledThread(PENDING_THREAD_ID))
    })

    apis.bootstrapApi.get.mockImplementation(() => afterMacrotask(bootstrapState(PENDING_THREAD_ID, [])))
    await act(async () => {
      await rendered.result.current.actions.handleAction('skip')
    })

    expect(apis.skipApi.unskip).toHaveBeenCalledWith(PENDING_THREAD_ID)
    expect(apis.bootstrapApi.get).toHaveBeenCalledTimes(1)
    await waitFor(() => {
      expect(rendered.result.current.bootstrap.data?.skipped_thread_ids).toEqual([])
    })
  })
})
