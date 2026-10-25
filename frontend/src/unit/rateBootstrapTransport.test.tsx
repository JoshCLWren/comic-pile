import { type ReactNode } from 'react'
import { act, renderHook, waitFor } from '@testing-library/react'
import { QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useRate } from '../hooks/useRate'
import type { RateMutationOutcome } from '../hooks/useRate'
import { publishRollBootstrap } from '../hooks/rollMutationReconciliation'
import { useRollBootstrap } from '../hooks/useRollBootstrap'
import { queryClient } from '../query/queryClient'
import { protectedRollMutationApi } from '../services/protectedRollMutationApi'
import { rollBootstrapApi } from '../services/rollBootstrapApi'
import { ToastProvider } from '../contexts/ToastProvider'
import type { RatePayload, Thread } from '../types'
import type { RollBootstrapResponse } from '../types/rollBootstrap'
import { useRollPageState } from '../pages/RollPage/useRollPageState'
import { useRollRating } from '../pages/RollPage/useRollRating'
import type { ThreadMetadata } from '../pages/RollPage/types'

vi.mock('../services/protectedRollMutationApi', () => ({
  protectedRollMutationApi: { rate: vi.fn(), snooze: vi.fn(), skip: vi.fn(), bootstrap: vi.fn() },
}))
vi.mock('../services/rollBootstrapApi', () => ({
  rollBootstrapApi: { get: vi.fn(), switchPrerequisite: vi.fn() },
}))
vi.mock('../query/cacheEffects', () => ({
  applyRatedThreadCache: vi.fn().mockResolvedValue(undefined),
}))

const mockedProtectedApi = vi.mocked(protectedRollMutationApi)
const mockedBootstrapApi = vi.mocked(rollBootstrapApi)

const THREAD: Thread = {
  id: 1,
  title: 'Saga',
  format: 'issue',
  issues_remaining: 4,
  total_issues: 10,
  queue_position: 2,
  status: 'active',
  is_blocked: false,
  blocking_reasons: [],
  last_activity_at: null,
  last_rating: null,
  notes: null,
  is_test: false,
  created_at: '2026-08-03T00:00:00Z',
}

const METADATA: ThreadMetadata = {
  id: 1,
  thread_id: 1,
  title: 'Saga',
  format: 'comic',
  issues_remaining: 5,
  queue_position: 1,
  total_issues: 10,
}

function bootstrapState(overrides: Partial<RollBootstrapResponse> = {}): RollBootstrapResponse {
  return {
    session_id: 1,
    user_id: 1,
    current_die: 8,
    manual_die: null,
    pending_thread_id: 1,
    last_rolled_result: 4,
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
    active_thread: {
      id: 1,
      title: 'Saga',
      format: 'comic',
      issues_remaining: 5,
      total_issues: 10,
      queue_position: 1,
      issue_number: '5',
      last_rolled_result: 4,
    },
    roll_pool: [{ id: 1, title: 'Saga', format: 'comic' }],
    snoozed_threads: [],
    snoozed_count: 0,
    skipped_thread_ids: [],
    skipped_threads: [],
    blocked_count: 0,
    blocked_threads: [],
    stale_thread_count: 1,
    stale_thread: {
      id: 1,
      title: 'Saga',
      format: 'comic',
      last_activity_at: '2026-07-01T00:00:00Z',
    },
    ...overrides,
  }
}

const authoritativeState = () => bootstrapState({
  pending_thread_id: null,
  last_rolled_result: null,
  active_thread: null,
  stale_thread_count: 0,
  stale_thread: null,
})

function wrap() {
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <ToastProvider>{children}</ToastProvider>
      </QueryClientProvider>
    )
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  queryClient.clear()
  mockedProtectedApi.rate.mockResolvedValue(THREAD)
  mockedBootstrapApi.get.mockResolvedValue(authoritativeState())
})

function useRateTransportHarness() {
  const bootstrap = useRollBootstrap()
  const rateMutation = useRate()
  const state = useRollPageState()
  const rating = useRollRating({
    state,
    bootstrap: bootstrap.data,
    rateMutation,
    dismissPendingMutation: { mutate: vi.fn().mockResolvedValue(undefined), isPending: false },
    refetchBootstrap: bootstrap.refetch,
  })
  return { bootstrap, rateMutation, state, rating }
}

async function enterRating(result: { current: ReturnType<typeof useRateTransportHarness> }) {
  await act(async () => {
    await result.current.rating.enterRatingView(THREAD.id, 4, METADATA)
  })
}

describe('Rate publishes one authoritative Roll bootstrap', () => {
  it('fetches bootstrap exactly once after a stale-eligible rating and applies stale state', async () => {
    mockedBootstrapApi.get
      .mockResolvedValueOnce(bootstrapState())
      .mockResolvedValueOnce(authoritativeState())

    const { result } = renderHook(() => useRateTransportHarness(), { wrapper: wrap() })
    await waitFor(() => expect(result.current.bootstrap.data).not.toBeNull())
    const initialFetches = mockedBootstrapApi.get.mock.calls.length

    await enterRating(result)
    await act(async () => {
      await result.current.rating.handleSubmitRating(false)
    })

    expect(mockedProtectedApi.rate).toHaveBeenCalledTimes(1)
    expect(mockedBootstrapApi.get.mock.calls.length - initialFetches).toBe(1)
    await waitFor(() => expect(result.current.bootstrap.data?.stale_thread_count).toBe(0))
    expect(result.current.bootstrap.data?.stale_thread).toBeNull()
    expect(result.current.bootstrap.data?.pending_thread_id).toBeNull()
    expect(result.current.bootstrap.data?.last_rolled_result).toBeNull()
    expect(result.current.state.errorMessage).toBe('')
  })

  it('keeps the transport count at one when the page callback settles after the zero-delay window', async () => {
    mockedBootstrapApi.get
      .mockResolvedValueOnce(bootstrapState())
      .mockResolvedValueOnce(authoritativeState())

    const { result } = renderHook(() => useRateTransportHarness(), { wrapper: wrap() })
    await waitFor(() => expect(result.current.bootstrap.data).not.toBeNull())
    const initialFetches = mockedBootstrapApi.get.mock.calls.length

    await enterRating(result)
    await act(async () => {
      await result.current.rating.handleSubmitRating(false)
    })
    // The page no longer depends on the zero-delay reconciliation window: drain
    // every scheduled callback and assert no late follow-up request appears.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 25))
    })

    expect(mockedProtectedApi.rate).toHaveBeenCalledTimes(1)
    expect(mockedBootstrapApi.get.mock.calls.length - initialFetches).toBe(1)
    await waitFor(() => expect(result.current.bootstrap.data?.stale_thread_count).toBe(0))
  })

  it('rates a simple-migration thread with the same single post-rate fetch', async () => {
    mockedBootstrapApi.get
      .mockResolvedValueOnce(bootstrapState({ active_thread: null }))
      .mockResolvedValueOnce(authoritativeState())

    const { result } = renderHook(() => useRateTransportHarness(), { wrapper: wrap() })
    await waitFor(() => expect(result.current.bootstrap.data).not.toBeNull())
    const initialFetches = mockedBootstrapApi.get.mock.calls.length

    await act(async () => {
      await result.current.rating.enterRatingView(THREAD.id, 4, {
        ...METADATA,
        issues_remaining: 0,
        total_issues: null,
      })
    })
    await act(async () => {
      await result.current.rating.handleSubmitRating(false)
    })
    expect(result.current.state.showSimpleMigration).toBe(true)
    expect(mockedProtectedApi.rate).not.toHaveBeenCalled()

    await act(async () => {
      result.current.rating.handleSimpleMigrationComplete('5')
      await new Promise((resolve) => setTimeout(resolve, 25))
    })

    expect(mockedProtectedApi.rate).toHaveBeenCalledTimes(1)
    expect(mockedBootstrapApi.get.mock.calls.length - initialFetches).toBe(1)
    await waitFor(() => expect(result.current.bootstrap.data?.stale_thread_count).toBe(0))
    expect(result.current.state.errorMessage).toBe('')
  })

  it('surfaces a failed authoritative refresh without repeating the rating mutation', async () => {
    mockedBootstrapApi.get
      .mockResolvedValueOnce(bootstrapState())
      .mockRejectedValue(new Error('bootstrap unavailable'))

    const { result } = renderHook(() => useRateTransportHarness(), { wrapper: wrap() })
    await waitFor(() => expect(result.current.bootstrap.data).not.toBeNull())
    const initialFetches = mockedBootstrapApi.get.mock.calls.length

    await enterRating(result)
    await act(async () => {
      await result.current.rating.handleSubmitRating(false)
      await new Promise((resolve) => setTimeout(resolve, 25))
    })

    expect(mockedProtectedApi.rate).toHaveBeenCalledTimes(1)
    expect(mockedBootstrapApi.get.mock.calls.length - initialFetches).toBe(1)
    expect(result.current.state.errorMessage).toBe(
      'Rating saved but failed to refresh. Please refresh the page.',
    )
  })
})

interface DirectRateMutation {
  mutate: (payload: RatePayload) => Promise<RateMutationOutcome>
  isPending: boolean
}

function useDirectRatingHarness(
  bootstrap: RollBootstrapResponse,
  rateMutation: DirectRateMutation,
  refetchBootstrap: () => Promise<RollBootstrapResponse | undefined>,
) {
  const state = useRollPageState()
  const rating = useRollRating({
    state,
    bootstrap,
    rateMutation,
    dismissPendingMutation: { mutate: vi.fn().mockResolvedValue(undefined), isPending: false },
    refetchBootstrap,
  })
  return { state, rating }
}

describe('useRollRating consumes the published authoritative snapshot', () => {
  it('never refetches when publication happens after the reconciliation window', async () => {
    const authoritative = authoritativeState()
    const mutate = vi.fn<(payload: RatePayload) => Promise<RateMutationOutcome>>()
    const rateMutation: DirectRateMutation = { mutate, isPending: false }
    const refetchBootstrap = vi.fn().mockResolvedValue(undefined)
    const { result } = renderHook(
      () => useDirectRatingHarness(bootstrapState(), rateMutation, refetchBootstrap),
      { wrapper: wrap() },
    )

    await act(async () => {
      await result.current.rating.enterRatingView(THREAD.id, 4, METADATA)
    })
    mutate.mockImplementation(async () => {
      // Mirrors useRate: publish the authoritative snapshot, then let the
      // event-loop reconciliation window expire before the page callback runs.
      publishRollBootstrap(authoritative)
      await new Promise((resolve) => setTimeout(resolve, 25))
      return { rate: THREAD, bootstrap: authoritative }
    })

    await act(async () => {
      await result.current.rating.handleSubmitRating(false)
    })

    expect(mockedProtectedApi.rate).not.toHaveBeenCalled()
    expect(mutate).toHaveBeenCalledTimes(1)
    expect(refetchBootstrap).not.toHaveBeenCalled()
    expect(result.current.state.errorMessage).toBe('')
  })

  it('reports a failed authoritative refresh on the simple-migration path without retrying the rating', async () => {
    const mutate = vi.fn<(payload: RatePayload) => Promise<RateMutationOutcome>>()
      .mockResolvedValue({ rate: THREAD, bootstrap: null })
    const rateMutation: DirectRateMutation = { mutate, isPending: false }
    const refetchBootstrap = vi.fn().mockResolvedValue(undefined)
    const { result } = renderHook(
      () => useDirectRatingHarness(
        bootstrapState({ active_thread: null, pending_thread_id: null }),
        rateMutation,
        refetchBootstrap,
      ),
      { wrapper: wrap() },
    )

    await act(async () => {
      await result.current.rating.enterRatingView(THREAD.id, 4, {
        ...METADATA,
        issues_remaining: 0,
        total_issues: null,
      })
    })
    await act(async () => {
      await result.current.rating.handleSubmitRating(false)
    })
    expect(result.current.state.showSimpleMigration).toBe(true)

    await act(async () => {
      result.current.rating.handleSimpleMigrationComplete('5')
      await new Promise((resolve) => setTimeout(resolve, 25))
    })

    expect(mutate).toHaveBeenCalledTimes(1)
    expect(refetchBootstrap).not.toHaveBeenCalled()
    expect(result.current.state.errorMessage).toBe(
      'Rating saved but failed to refresh. Please refresh the page.',
    )
  })
})
