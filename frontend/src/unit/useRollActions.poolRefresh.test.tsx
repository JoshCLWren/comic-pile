/**
 * #4276 — the Roll pool action sheet reports a failed pool refresh without
 * issuing a second request.
 *
 * The move/shuffle hooks own the retained roll-bootstrap invalidation, so the
 * action handler must not call `refetchBootstrap()` again. The single-refresh
 * contract still has to report a refresh that failed, and it does so by reading
 * the already-settled query state.
 *
 * These cases pin that the state read happens AFTER the mutation settles, which
 * is the only point at which the error is observable. The bootstrap query
 * succeeds on mount and fails only on the invalidation refetch, so an error at
 * the handler's read can only come from the mutation's own awaited pass. If the
 * read moved ahead of that pass it would still see the successful mount state,
 * the failure would be silently missed, and the reader would be told the move
 * succeeded.
 */
import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import { QueryClientProvider, useQuery } from '@tanstack/react-query'
import type { NavigateFunction } from 'react-router-dom'
import { useRollActions } from '../pages/RollPage/useRollActions'
import { useRollPageState } from '../pages/RollPage/useRollPageState'
import { useMoveToBack, useMoveToFront, useShuffleQueue } from '../hooks/useQueue'
import { invalidateAfterQueueMovement } from '../query/cacheEffects'
import { queryClient } from '../query/queryClient'
import { queryKeys } from '../query/queryKeys'
import type { RollBootstrapResponse, RollBootstrapThread } from '../types/rollBootstrap'

/**
 * The production invalidation pass, bound to the shared query client.
 *
 * The move and shuffle hooks call this inside their mutation, and it is the
 * pass whose awaited refetch makes the settled error state observable.
 */
const realInvalidation = (client: typeof queryClient) => invalidateAfterQueueMovement(client)

/** A bootstrap payload the action sheet can render; the pool content is irrelevant here. */
function bootstrapWith(overrides: Partial<RollBootstrapResponse> = {}): RollBootstrapResponse {
  // SAFETY: the literal supplies every required bootstrap field; the spread only narrows them
  return {
    session_id: 1,
    user_id: 1,
    current_die: 6,
    manual_die: null,
    pending_thread_id: null,
    last_rolled_result: null,
    session_mode: null,
    active_thread: null,
    roll_pool: [],
    snoozed_threads: [],
    snoozed_count: 0,
    skipped_thread_ids: [],
    skipped_threads: [],
    ...overrides,
  } as RollBootstrapResponse
}

function pooledThread(id: number): RollBootstrapThread {
  return { id, title: `Series ${id}`, format: 'Comic' }
}

const bootstrapKey = queryKeys.roll.bootstrap()

/**
 * Refetch counter for the observed bootstrap query.
 *
 * The first fetch (mount) succeeds so the query is healthy; every later fetch
 * is the invalidation refetch and fails. A non-empty `error` at the handler's
 * read therefore proves the mutation's own awaited refetch already ran.
 */
let bootstrapFetches = 0

function resetBootstrapFetches(): void {
  bootstrapFetches = 0
}

/**
 * Observe the bootstrap query so the invalidation refetches it.
 *
 * TanStack Query's `invalidateQueries` defaults to `refetchType: 'active'`, so
 * the query only refetches while something observes it. The harness mounts a
 * real observer for the bootstrap key, exactly as the Roll page's
 * `useRollBootstrap` does while the page is mounted.
 */
function useBootstrapObserver(): void {
  useQuery({
    queryKey: bootstrapKey,
    queryFn: async () => {
      bootstrapFetches += 1
      if (bootstrapFetches === 1) {
        return bootstrapWith()
      }
      throw new Error('bootstrap unavailable')
    },
    retry: false,
    staleTime: 0,
  })
}

interface Harness {
  result: { current: { state: ReturnType<typeof useRollPageState>; actions: ReturnType<typeof useRollActions> } }
  refetchBootstrap: ReturnType<typeof vi.fn>
}

/**
 * Render the action sheet with the REAL move/shuffle hooks.
 *
 * The production contract under test is that the hook owns the queue-movement
 * invalidation, so the handler's settled-state read happens after that pass.
 * Stubbing the mutation would remove the very pass being relied on, so the
 * real hooks are used and only their API transport is replaced.
 */
function renderActionSheet(bootstrap: RollBootstrapResponse): Harness {
  const moveToFrontMutate = vi.fn(() => Promise.resolve())
  const moveToBackMutate = vi.fn(() => Promise.resolve())
  const shuffleMutate = vi.fn(() => Promise.resolve())
  const refetchBootstrap = vi.fn(() => Promise.resolve(bootstrap))

  const { result } = renderHook(() => {
    const state = useRollPageState()
    // Observe the bootstrap query so the invalidation refetches it, the way
    // the Roll page's own `useRollBootstrap` does while the page is mounted.
    useBootstrapObserver()
    // The real queue hooks must run inside the provider so they read the
    // shared client, exactly as the production Roll page composes them. The
    // doubles supply the complete `QueueApi` surface with its declared
    // signatures, so no cast is needed.
    const moveToFront = useMoveToFront({
      api: {
        moveToPosition: vi.fn(() => Promise.resolve()),
        moveToFront: moveToFrontMutate,
        moveToBack: moveToBackMutate,
        shuffle: shuffleMutate,
      },
      invalidate: realInvalidation,
    })
    const moveToBack = useMoveToBack({
      api: {
        moveToPosition: vi.fn(() => Promise.resolve()),
        moveToFront: moveToFrontMutate,
        moveToBack: moveToBackMutate,
        shuffle: shuffleMutate,
      },
      invalidate: realInvalidation,
    })
    const shuffleQueue = useShuffleQueue({
      api: {
        moveToPosition: vi.fn(() => Promise.resolve()),
        moveToFront: moveToFrontMutate,
        moveToBack: moveToBackMutate,
        shuffle: shuffleMutate,
      },
      invalidate: realInvalidation,
    })
    const actions = useRollActions({
      state,
      bootstrap,
      rollPool: bootstrap.roll_pool,
      // SAFETY: the hook only calls navigate in routing flows this test never triggers
      navigate: vi.fn() as NavigateFunction,
      mutations: {
        setDieMutation: { mutate: vi.fn(() => Promise.resolve()), isPending: false },
        rollMutation: { mutate: vi.fn(), isPending: false },
        snoozeMutation: {
          mutate: vi.fn(() => Promise.resolve({ response: undefined, refreshed: true, refreshError: null })),
          isPending: false,
        },
        unsnoozeMutation: { mutate: vi.fn(() => Promise.resolve()), isPending: false },
        skipMutation: {
          mutate: vi.fn(() => Promise.resolve({ response: undefined, refreshed: true, refreshError: null })),
          isPending: false,
        },
        unskipMutation: { mutate: vi.fn(() => Promise.resolve()), isPending: false },
        moveToFrontMutation: { mutate: moveToFront.mutate, isPending: moveToFront.isPending },
        moveToBackMutation: { mutate: moveToBack.mutate, isPending: moveToBack.isPending },
        shuffleQueueMutation: { mutate: shuffleQueue.mutate, isPending: shuffleQueue.isPending },
      },
      refetchBootstrap,
      enterRatingView: vi.fn(() => Promise.resolve()),
      // SAFETY: the hook only calls setPending; the stub omits the rest of the API surface
      threadsApi: { setPending: vi.fn() } as never,
    })
    return { state, actions }
  }, {
    // The real queue hooks read the client from context.
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    ),
  })

  return { result, refetchBootstrap }
}

/** Await the mount fetch so the query is healthy before the action runs. */
async function settleMount(): Promise<void> {
  await act(async () => {
    await Promise.resolve()
  })
  expect(bootstrapFetches).toBe(1)
  expect(queryClient.getQueryState(bootstrapKey)?.status).toBe('success')
}

describe('Roll pool action sheet pool-refresh feedback (#4276)', () => {
  beforeEach(() => {
    queryClient.clear()
    resetBootstrapFetches()
  })

  afterEach(() => {
    queryClient.clear()
    resetBootstrapFetches()
  })

  it('reports a failed pool refresh after a move-to-front, with no second request', async () => {
    const bootstrap = bootstrapWith({ roll_pool: [pooledThread(1)] })
    const { result, refetchBootstrap } = renderActionSheet(bootstrap)
    await settleMount()

    act(() => {
      result.current.state.setSelectedThread(pooledThread(1))
    })

    await act(async () => {
      await result.current.actions.handleAction('move-front')
    })

    // The invalidation pass inside the mutation refetched and failed, so the
    // handler observed the error rather than the healthy mount state.
    expect(bootstrapFetches).toBe(2)
    expect(queryClient.getQueryState(bootstrapKey)?.error).not.toBeNull()
    // The single-refresh contract: the handler must not issue another request.
    expect(refetchBootstrap).not.toHaveBeenCalled()
    expect(result.current.state.errorMessage).toContain('did not refresh')
  })

  it('reports a failed pool refresh after a move-to-back, with no second request', async () => {
    const bootstrap = bootstrapWith({ roll_pool: [pooledThread(1)] })
    const { result, refetchBootstrap } = renderActionSheet(bootstrap)
    await settleMount()

    act(() => {
      result.current.state.setSelectedThread(pooledThread(1))
    })

    await act(async () => {
      await result.current.actions.handleAction('move-back')
    })

    expect(bootstrapFetches).toBe(2)
    expect(queryClient.getQueryState(bootstrapKey)?.error).not.toBeNull()
    expect(refetchBootstrap).not.toHaveBeenCalled()
    expect(result.current.state.errorMessage).toContain('did not refresh')
  })

  it('keeps the shuffle dialog open and reports the failed pool refresh', async () => {
    const bootstrap = bootstrapWith({ roll_pool: [pooledThread(1)] })
    const { result, refetchBootstrap } = renderActionSheet(bootstrap)
    await settleMount()

    // The reader has the confirmation open and is committing it.
    act(() => {
      result.current.state.setIsShuffleOpen(true)
    })
    expect(result.current.state.isShuffleOpen).toBe(true)

    await act(async () => {
      await result.current.actions.performShuffle()
    })

    expect(bootstrapFetches).toBe(2)
    expect(queryClient.getQueryState(bootstrapKey)?.error).not.toBeNull()
    expect(refetchBootstrap).not.toHaveBeenCalled()
    // The dialog must stay open so the reader can retry, with the reason shown
    // inside it (a toast would paint below the modal layer, #4193).
    expect(result.current.state.isShuffleOpen).toBe(true)
    expect(result.current.state.shuffleError).toContain('did not refresh')
  })
})
