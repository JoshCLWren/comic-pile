/**
 * Issue #4142 — a successful Skip must own exactly one authoritative
 * `GET /api/v1/roll/bootstrap`. These tests compose the real skip mutation,
 * the real bootstrap query hook, and each Roll caller (rating view and pool
 * action sheet) so the assertion counts actual API `get` calls instead of a
 * stubbed `refetchBootstrap`.
 *
 * The transport count alone cannot prove the caller stopped refreshing:
 * publishing a fresh snapshot opens a zero-delay `justReconciledRef` window in
 * `useRollBootstrap`, so a caller-driven `await refetchBootstrap()` that runs
 * before the mutation's promise resolves is answered from the cache and never
 * reaches the transport. Every harness therefore also wraps the
 * `refetchBootstrap` callback it passes to the caller in a spy and asserts the
 * caller never invokes it, which is what makes a returning redundant refresh
 * fail these tests.
 */
import { type ReactNode } from 'react'
import { act, renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { NavigateFunction } from 'react-router-dom'
import { ToastProvider } from '../contexts/ToastProvider'
import { useSkip, useUnskip } from '../hooks/useSkip'
import { useRollBootstrap } from '../hooks/useRollBootstrap'
import { useRollPageState } from '../pages/RollPage/useRollPageState'
import { useRollPendingSession } from '../pages/RollPage/useRollPendingSession'
import { useRollRating } from '../pages/RollPage/useRollRating'
import { useRollSkip } from '../pages/RollPage/useRollSkip'
import { useRollActions } from '../pages/RollPage/useRollActions'
import { threadsApi } from '../services/api-threads'
import type { RollResponse } from '../types'
import type { RollBootstrapResponse, RollBootstrapThread } from '../types/rollBootstrap'

const PENDING_THREAD_ID = 8
/** Replacement pending read returned by a committed skip of the original one. */
const REPLACEMENT_THREAD_ID = 9

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
  // The spy is stable across renders on purpose: a per-render spy would hide a
  // caller refresh behind whichever instance the assertion happened to read.
  // Spying on the callback the caller is given is the only way to observe a
  // redundant refresh, because `useRollBootstrap` answers it from the
  // reconciliation window without a transport call (see the file header).
  let refetchImpl: () => Promise<RollBootstrapResponse> = () => Promise.reject(new Error('bootstrap not loaded'))
  const refetchBootstrap = vi.fn(() => refetchImpl())

  const rendered = renderHook(() => {
    const state = useRollPageState()
    const bootstrap = useRollBootstrap(apis.bootstrapApi)
    const skipMutation = useSkip(apis)
    const unskipMutation = useUnskip(apis)
    refetchImpl = bootstrap.refetch

    const skip = useRollSkip({
      state,
      skipMutation,
      unskipMutation,
      refetchBootstrap,
      enterRatingView,
      expectedPendingThreadId: bootstrap.data?.pending_thread_id ?? undefined,
      onRefreshFailed,
    })

    return { state, skip, bootstrap }
  }, { wrapper })

  return { rendered, onRefreshFailed, enterRatingView, refetchBootstrap }
}

function renderActionSheetFlow(apis: Apis) {
  const wrapper = makeWrapper()
  const onSkipRefreshFailed = vi.fn()
  const enterRatingView = vi.fn().mockResolvedValue(undefined)
  // See `renderRatingSkipFlow`: the callback spy catches a caller-driven
  // refresh that the reconciliation window would otherwise mask.
  let refetchImpl: () => Promise<RollBootstrapResponse> = () => Promise.reject(new Error('bootstrap not loaded'))
  const refetchBootstrap = vi.fn(() => refetchImpl())

  const rendered = renderHook(() => {
    const state = useRollPageState()
    const bootstrap = useRollBootstrap(apis.bootstrapApi)
    const skipMutation = useSkip(apis)
    const unskipMutation = useUnskip(apis)
    refetchImpl = bootstrap.refetch

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
      refetchBootstrap,
      enterRatingView,
      threadsApi,
      onSkipRefreshFailed,
    })

    return { state, actions, bootstrap }
  }, { wrapper })

  return { rendered, onSkipRefreshFailed, refetchBootstrap }
}

/**
 * Composes the real `useRollRating.enterRatingView` and the real
 * `useRollPendingSession` so a stale snapshot has every chance to reopen the
 * thread a skip just consumed, exactly as it does on the Roll page.
 */
function renderPendingSessionSkipFlow(apis: Apis) {
  const wrapper = makeWrapper()
  const onRefreshFailed = vi.fn()
  // See `renderRatingSkipFlow`: one stable callback spy for the whole flow.
  let refetchImpl: () => Promise<RollBootstrapResponse> = () => Promise.reject(new Error('bootstrap not loaded'))
  const refetchBootstrap = vi.fn(() => refetchImpl())

  const rendered = renderHook(() => {
    const state = useRollPageState()
    const bootstrap = useRollBootstrap(apis.bootstrapApi)
    const skipMutation = useSkip(apis)
    const unskipMutation = useUnskip(apis)
    refetchImpl = bootstrap.refetch
    const rating = useRollRating({
      state,
      bootstrap: bootstrap.data,
      rateMutation: { mutate: vi.fn(), isPending: false },
      dismissPendingMutation: { mutate: vi.fn(), isPending: false },
      refetchBootstrap,
    })
    useRollPendingSession({
      state,
      bootstrap: bootstrap.data,
      rollPool: bootstrap.data?.roll_pool ?? [],
    })

    const skip = useRollSkip({
      state,
      skipMutation,
      unskipMutation,
      refetchBootstrap,
      enterRatingView: rating.enterRatingView,
      expectedPendingThreadId: bootstrap.data?.pending_thread_id ?? undefined,
      onRefreshFailed,
    })

    return { state, skip, bootstrap }
  }, { wrapper })

  return { rendered, onRefreshFailed, refetchBootstrap }
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
    const { rendered, enterRatingView, refetchBootstrap } = renderRatingSkipFlow(apis)
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
    // A reintroduced caller refresh may be answered from the reconciliation
    // window instead of the transport, so the callback must stay untouched.
    expect(refetchBootstrap).not.toHaveBeenCalled()
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
    const { rendered, refetchBootstrap } = renderActionSheetFlow(apis)
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
    // See the rating-view test: the callback spy is what detects a duplicate
    // caller refresh inside the reconciliation window.
    expect(refetchBootstrap).not.toHaveBeenCalled()
  })

  it('rating view: an exhausted refresh is reported without a caller retry', async () => {
    const apis = makeApis()
    const refreshFailure = new Error('bootstrap unavailable')
    apis.bootstrapApi.get.mockImplementation(() => afterMacrotask(bootstrapState(PENDING_THREAD_ID)))
    apis.protectedApi.skip.mockImplementation(() => afterMacrotask(skipResponse(PENDING_THREAD_ID)))
    const { rendered, onRefreshFailed, enterRatingView, refetchBootstrap } = renderRatingSkipFlow(apis)
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
    expect(refetchBootstrap).not.toHaveBeenCalled()
    expect(onRefreshFailed).toHaveBeenCalledWith(refreshFailure)
    // The committed skip still advances the rating view from its response.
    expect(enterRatingView).toHaveBeenCalledTimes(1)
  })

  it('action sheet: an exhausted refresh is reported without a caller retry', async () => {
    const apis = makeApis()
    const refreshFailure = new Error('bootstrap unavailable')
    apis.bootstrapApi.get.mockImplementation(() => afterMacrotask(bootstrapState(PENDING_THREAD_ID)))
    apis.protectedApi.skip.mockImplementation(() => afterMacrotask(skipResponse(PENDING_THREAD_ID)))
    const { rendered, onSkipRefreshFailed, refetchBootstrap } = renderActionSheetFlow(apis)
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
    expect(refetchBootstrap).not.toHaveBeenCalled()
    expect(onSkipRefreshFailed).toHaveBeenCalledWith(refreshFailure)
  })

  it('an exhausted post-skip refresh never reopens the skipped thread', async () => {
    const apis = makeApis()
    const staleSnapshot = {
      ...bootstrapState(PENDING_THREAD_ID),
      roll_pool: [pooledThread(PENDING_THREAD_ID), pooledThread(REPLACEMENT_THREAD_ID)],
    }
    apis.bootstrapApi.get.mockImplementation(() => afterMacrotask(staleSnapshot))
    apis.protectedApi.skip.mockImplementation(() => afterMacrotask(skipResponse(REPLACEMENT_THREAD_ID)))
    const { rendered, refetchBootstrap } = renderPendingSessionSkipFlow(apis)
    await settleInitialBootstrap(apis, rendered)
    apis.bootstrapApi.get.mockImplementation(() => Promise.reject(new Error('bootstrap unavailable')))

    // The pending-session hook hydrated the original pending read, so the
    // reader is rating the series this skip is about to consume.
    await waitFor(() => {
      expect(rendered.result.current.state.selectedThreadId).toBe(PENDING_THREAD_ID)
    })
    expect(rendered.result.current.state.isRatingView).toBe(true)

    await act(async () => {
      await rendered.result.current.skip.handleSkip()
    })
    await act(async () => {
      await afterMacrotask(null)
    })

    expect(apis.protectedApi.skip).toHaveBeenCalledTimes(1)
    // Both bounded refresh attempts failed, so the pre-skip snapshot — whose
    // pending id is the thread the skip just consumed — is still published.
    expect(apis.bootstrapApi.get).toHaveBeenCalledTimes(2)
    expect(rendered.result.current.bootstrap.data?.pending_thread_id).toBe(PENDING_THREAD_ID)
    expect(refetchBootstrap).not.toHaveBeenCalled()
    // The stale pending id must not steal the rating view from the replacement.
    expect(rendered.result.current.state.selectedThreadId).toBe(REPLACEMENT_THREAD_ID)
    expect(rendered.result.current.state.activeRatingThread?.id).toBe(REPLACEMENT_THREAD_ID)
    expect(rendered.result.current.state.isRatingView).toBe(true)
  })

  it('a successful post-skip refresh releases the stale-pending guard', async () => {
    const apis = makeApis()
    const firstSnapshot = {
      ...bootstrapState(PENDING_THREAD_ID),
      roll_pool: [pooledThread(PENDING_THREAD_ID), pooledThread(REPLACEMENT_THREAD_ID)],
    }
    apis.bootstrapApi.get.mockImplementation(() => afterMacrotask(firstSnapshot))
    apis.protectedApi.skip.mockImplementation(() => afterMacrotask(skipResponse(REPLACEMENT_THREAD_ID)))
    const { rendered, refetchBootstrap } = renderPendingSessionSkipFlow(apis)
    await settleInitialBootstrap(apis, rendered)
    await waitFor(() => {
      expect(rendered.result.current.state.selectedThreadId).toBe(PENDING_THREAD_ID)
    })

    // The mutation's own refresh publishes the replacement as the pending read.
    apis.bootstrapApi.get.mockImplementation(() => afterMacrotask({
      ...bootstrapState(REPLACEMENT_THREAD_ID),
      roll_pool: [pooledThread(PENDING_THREAD_ID), pooledThread(REPLACEMENT_THREAD_ID)],
    }))

    await act(async () => {
      await rendered.result.current.skip.handleSkip()
    })
    await act(async () => {
      await afterMacrotask(null)
    })

    expect(apis.bootstrapApi.get).toHaveBeenCalledTimes(1)
    expect(refetchBootstrap).not.toHaveBeenCalled()
    expect(rendered.result.current.bootstrap.data?.pending_thread_id).toBe(REPLACEMENT_THREAD_ID)
    expect(rendered.result.current.state.selectedThreadId).toBe(REPLACEMENT_THREAD_ID)
    expect(rendered.result.current.state.activeRatingThread?.id).toBe(REPLACEMENT_THREAD_ID)
  })

  it('unskip from the rating view refreshes once and drops skipped membership', async () => {
    const apis = makeApis()
    apis.bootstrapApi.get.mockImplementation(() => afterMacrotask(bootstrapState(PENDING_THREAD_ID, [PENDING_THREAD_ID])))
    apis.skipApi.unskip.mockResolvedValue(undefined)
    const { rendered, refetchBootstrap } = renderRatingSkipFlow(apis)
    await settleInitialBootstrap(apis, rendered)

    apis.bootstrapApi.get.mockImplementation(() => afterMacrotask(bootstrapState(PENDING_THREAD_ID, [])))
    await act(async () => {
      await rendered.result.current.skip.handleUnskip(PENDING_THREAD_ID)
    })

    expect(apis.skipApi.unskip).toHaveBeenCalledWith(PENDING_THREAD_ID)
    expect(refetchBootstrap).toHaveBeenCalledTimes(1)
    expect(apis.bootstrapApi.get).toHaveBeenCalledTimes(1)
    await waitFor(() => {
      expect(rendered.result.current.bootstrap.data?.skipped_thread_ids).toEqual([])
    })
  })

  it('unskip from the action sheet refreshes once and drops skipped membership', async () => {
    const apis = makeApis()
    apis.bootstrapApi.get.mockImplementation(() => afterMacrotask(bootstrapState(PENDING_THREAD_ID, [PENDING_THREAD_ID])))
    apis.skipApi.unskip.mockResolvedValue(undefined)
    const { rendered, refetchBootstrap } = renderActionSheetFlow(apis)
    await settleInitialBootstrap(apis, rendered)

    act(() => {
      rendered.result.current.state.setSelectedThread(pooledThread(PENDING_THREAD_ID))
    })

    apis.bootstrapApi.get.mockImplementation(() => afterMacrotask(bootstrapState(PENDING_THREAD_ID, [])))
    await act(async () => {
      await rendered.result.current.actions.handleAction('skip')
    })

    expect(apis.skipApi.unskip).toHaveBeenCalledWith(PENDING_THREAD_ID)
    expect(refetchBootstrap).toHaveBeenCalledTimes(1)
    expect(apis.bootstrapApi.get).toHaveBeenCalledTimes(1)
    await waitFor(() => {
      expect(rendered.result.current.bootstrap.data?.skipped_thread_ids).toEqual([])
    })
  })
})
