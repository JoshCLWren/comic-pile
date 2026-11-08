import { act, renderHook } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useSetDie } from '../hooks/useRoll'
import { useRatingView } from '../pages/RollPage/useRatingView'
import { readerContextApi } from '../services/api-reader-context'
import type { RollApi } from '../services/apiTypes'
import { queryClient } from '../query/queryClient'
import { queryKeys } from '../query/queryKeys'
import type { RollPageState, RollPageStateSetters } from '../pages/RollPage/useRollPageState'
import type { RatingThread } from '../pages/RollPage/types'

vi.mock('../services/api-reader-context', () => ({
  readerContextApi: { get: vi.fn().mockResolvedValue(null) },
}))

const getReaderContext = vi.mocked(readerContextApi.get)

const setDie = vi.fn<(die: number) => Promise<void>>().mockResolvedValue(undefined)

const rollApi: RollApi = {
  roll: vi.fn(),
  override: vi.fn(),
  dismissPending: vi.fn(),
  reroll: vi.fn(),
  setDie,
  reset: vi.fn().mockResolvedValue({ die: 6, replayed: false }),
}

const ACTIVE_THREAD: RatingThread = {
  id: 1,
  title: 'Saga',
  format: 'Comic',
  issues_remaining: 5,
  total_issues: 10,
  queue_position: 0,
  issue_id: 100,
}

function mockState(
  overrides: Partial<RollPageState & RollPageStateSetters> = {},
): RollPageState & RollPageStateSetters {
  const noop = vi.fn()
  return {
    isRolling: false,
    rolledResult: null,
    selectedThreadId: null,
    isOverrideOpen: false,
    overrideThreadId: '',
    overrideErrorMessage: '',
    snoozedExpanded: false,
    isDieModalOpen: false,
    isSetCurrentIssueOpen: false,
    selectedThread: null,
    isActionSheetOpen: false,
    activeRatingThread: ACTIVE_THREAD,
    showMigrationDialog: false,
    threadToMigrate: null,
    showSimpleMigration: false,
    isRatingView: true,
    isShuffleOpen: false,
    shuffleError: '',
    rating: 3.0,
    errorMessage: '',
    suppressPendingAutoOpenRef: { current: false },
    rollIntervalRef: { current: null },
    rollTimeoutRef: { current: null },
    setIsRolling: noop,
    setRolledResult: noop,
    setSelectedThreadId: noop,
    setIsOverrideOpen: noop,
    setOverrideThreadId: noop,
    setOverrideErrorMessage: noop,
    setSnoozedExpanded: noop,
    setIsDieModalOpen: noop,
    setIsSetCurrentIssueOpen: noop,
    setSelectedThread: noop,
    setIsActionSheetOpen: noop,
    setActiveRatingThread: noop,
    setShowMigrationDialog: noop,
    setThreadToMigrate: noop,
    setShowSimpleMigration: noop,
    setIsRatingView: noop,
    setIsShuffleOpen: noop,
    setShuffleError: noop,
    setRating: noop,
    setErrorMessage: noop,
    ...overrides,
  }
}

function wrapper(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

function testClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
}

function renderUseRatingView(currentDie = 6) {
  return renderHook(
    () =>
      useRatingView({
        state: mockState(),
        currentDie,
        readerContextRequested: false,
        readingContextRequested: false,
        readingBoundariesRequested: false,
        readingOrders: [],
        connectedThreads: [],
        onShowContext: vi.fn(),
        onShowBoundaries: vi.fn(),
        readingOrdersIsLoading: false,
        readingOrdersError: null,
        connectedThreadsIsLoading: false,
        connectedThreadsError: null,
        rating: {
          updateRatingUI: vi.fn(),
          handleSubmitRating: vi.fn().mockResolvedValue(undefined),
          handleCancelRating: vi.fn().mockResolvedValue(undefined),
          handleRefreshThread: vi.fn().mockResolvedValue(undefined),
          enterRatingView: vi.fn().mockResolvedValue(undefined),
        },
        snooze: { handleSnooze: vi.fn().mockResolvedValue(undefined) },
        rateMutation: { isPending: false },
        snoozeMutation: { isPending: false },
        dismissPendingMutation: { isPending: false },
        ratingViewTopRef: { current: null },
      }),
    { wrapper: wrapper(testClient()) },
  )
}

beforeEach(() => {
  getReaderContext.mockClear()
  setDie.mockClear()
})

describe('rating view die projection (#4352 contract-after)', () => {
  it('reports automatic mode while no die is pinned', () => {
    const { result } = renderUseRatingView()

    expect(result.current.manualDie).toBeNull()
    expect(result.current.currentDie).toBe(6)
    expect(result.current.predictedDie).toBe(8)
  })

  it('keeps the ladder readout at a pinned die now that manual mode is gone (#3144 retired)', () => {
    // `RollPage` derives the selected die during render (#4352) and passes it
    // to `useRatingView`, so the card sees the same die from both props.
    // Bootstrap no longer carries manual_die, so manualDie is always null and
    // the card always shows the ladder move.
    const { result } = renderUseRatingView(20)

    expect(result.current.manualDie).toBeNull()
    expect(result.current.currentDie).toBe(20)
  })

  it('treats a not-yet-loaded scoped die as automatic mode', () => {
    const { result } = renderUseRatingView()

    expect(result.current.manualDie).toBeNull()
  })
})

describe('die-mode mutations invalidate scoped die-state', () => {
  it('pinning a die invalidates the scoped die-state and bootstrap', async () => {
    const invalidateQueries = vi
      .spyOn(queryClient, 'invalidateQueries')
      .mockResolvedValue(undefined)
    const { result } = renderHook(() => useSetDie(rollApi), {
      wrapper: wrapper(testClient()),
    })

    await act(async () => {
      await result.current.mutate(20)
    })

    expect(setDie).toHaveBeenCalledWith(20)
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.roll.bootstrap(),
      exact: true,
    })
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.session.current(),
      exact: true,
    })
    // #4352: the header is render-derived from the scoped die-state query, so
    // the mutation must invalidate it or the header keeps showing the old
    // die until the stale window elapses.
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.roll.dieState(),
      exact: true,
    })

    invalidateQueries.mockRestore()
  })

  it('die-scoped invalidation covers the header update without a bootstrap-only refetch', async () => {
    // `handleSetDie` in `useRollActions` no longer calls `setCurrentDie`; the
    // only signal the header needs is the die-state query being invalidated
    // and refetched. Asserting the die-state key is in the invalidation set
    // (and not relying solely on the bootstrap key) proves the header path.
    const invalidateQueries = vi
      .spyOn(queryClient, 'invalidateQueries')
      .mockResolvedValue(undefined)
    const { result } = renderHook(() => useSetDie(rollApi), {
      wrapper: wrapper(testClient()),
    })

    await act(async () => {
      await result.current.mutate(12)
    })

    expect(setDie).toHaveBeenCalledWith(12)
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.roll.dieState(),
      exact: true,
    })

    invalidateQueries.mockRestore()
  })
})
