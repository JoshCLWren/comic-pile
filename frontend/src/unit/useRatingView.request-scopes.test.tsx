import { act, renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, expect, it, vi } from 'vitest'
import { useRatingView } from '../pages/RollPage/useRatingView'
import { readerContextApi } from '../services/api-reader-context'
import type { RollPageState, RollPageStateSetters } from '../pages/RollPage/useRollPageState'
import type { RatingThread } from '../pages/RollPage/types'
import type { ReaderContextResponse } from '../services/api-reader-context'

vi.mock('../services/api-reader-context', () => ({
  readerContextApi: { get: vi.fn() },
}))

const getReaderContext = vi.mocked(readerContextApi.get)

const ACTIVE_THREAD: RatingThread = {
  id: 1,
  title: 'Saga',
  format: 'Comic',
  issues_remaining: 5,
  total_issues: 10,
  queue_position: 0,
  issue_id: 100,
}

const READER_CONTEXT: ReaderContextResponse = {
  issue_id: 100,
  series: {
    identity_source: 'unavailable',
    canonical_series_id: null,
    series_name: 'Saga',
    average_rating: null,
    ratings_count: 0,
    previous_issue: null,
    recent_ratings: [],
    highest_rating: null,
    lowest_rating: null,
  },
  crossovers: [],
  local_chain: { issues: [], edges: [] },
}

function createWrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

function mockState(overrides: Partial<RollPageState & RollPageStateSetters> = {}): RollPageState & RollPageStateSetters {
  return {
    isRolling: false,
    rolledResult: null,
    selectedThreadId: null,
    currentDie: 6,
    diceState: 'idle',
    staleThread: null,
    staleThreadCount: 0,
    isOverrideOpen: false,
    overrideThreadId: '',
    overrideErrorMessage: '',
    snoozedExpanded: false,
    skippedExpanded: false,
    blockedExpanded: false,
    staleExpanded: false,
    isDieModalOpen: false,
    isSetCurrentIssueOpen: false,
    selectedThread: null,
    isActionSheetOpen: false,
    activeRatingThread: null,
    blockingDependencyMap: {},
    showMigrationDialog: false,
    threadToMigrate: null,
    showSimpleMigration: false,
    isRatingView: false,
    rating: 3.0,
    errorMessage: '',
    suppressPendingAutoOpenRef: { current: false },
    rollIntervalRef: { current: null },
    rollTimeoutRef: { current: null },
    setIsRolling: vi.fn(),
    setRolledResult: vi.fn(),
    setSelectedThreadId: vi.fn(),
    setCurrentDie: vi.fn(),
    setDiceState: vi.fn(),
    setStaleThread: vi.fn(),
    setStaleThreadCount: vi.fn(),
    setIsOverrideOpen: vi.fn(),
    setOverrideThreadId: vi.fn(),
    setOverrideErrorMessage: vi.fn(),
    setSnoozedExpanded: vi.fn(),
    setSkippedExpanded: vi.fn(),
    setBlockedExpanded: vi.fn(),
    setStaleExpanded: vi.fn(),
    setIsDieModalOpen: vi.fn(),
    setIsSetCurrentIssueOpen: vi.fn(),
    setSelectedThread: vi.fn(),
    setIsActionSheetOpen: vi.fn(),
    setActiveRatingThread: vi.fn(),
    setBlockingDependencyMap: vi.fn(),
    setShowMigrationDialog: vi.fn(),
    setThreadToMigrate: vi.fn(),
    setShowSimpleMigration: vi.fn(),
    setIsRatingView: vi.fn(),
    setRating: vi.fn(),
    setErrorMessage: vi.fn(),
    ...overrides,
  }
}

const rating = {
  updateRatingUI: vi.fn(),
  handleSubmitRating: vi.fn().mockResolvedValue(undefined),
  handleCancelRating: vi.fn().mockResolvedValue(undefined),
  handleRefreshThread: vi.fn().mockResolvedValue(undefined),
  enterRatingView: vi.fn().mockResolvedValue(undefined),
}
const snooze = { handleSnooze: vi.fn() }
const rateMutation = { isPending: false }
const snoozeMutation = { isPending: false }
const dismissPendingMutation = { isPending: false }
const skipMutation = { isPending: false }
const ratingViewTopRef = { current: null }

interface ScopeOverrides {
  readerContextRequested?: boolean
  readingContextRequested?: boolean
  readingBoundariesRequested?: boolean
  readingOrdersIsLoading?: boolean
  readingOrdersError?: Error | null
  connectedThreadsIsLoading?: boolean
  connectedThreadsError?: Error | null
}

function renderRatingView(initialScopes: ScopeOverrides = {}) {
  const state = mockState({ activeRatingThread: ACTIVE_THREAD })
  const params = {
    state,
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
    rating,
    snooze,
    onSkip: vi.fn(),
    rateMutation,
    snoozeMutation,
    dismissPendingMutation,
    skipMutation,
    ratingViewTopRef,
    ...initialScopes,
  }
  const { result, rerender } = renderHook((props: typeof params) => useRatingView(props), {
    wrapper: createWrapper(),
    initialProps: params,
  })
  const setScopes = (scopes: ScopeOverrides) => rerender({ ...params, ...scopes })
  return { result, setScopes, state }
}

beforeEach(() => {
  getReaderContext.mockReset()
  getReaderContext.mockResolvedValue(READER_CONTEXT)
})

it('rating entry fetches no reader context while every optional scope is closed', async () => {
  const { result } = renderRatingView()

  expect(result.current.isReaderContextLoading).toBe(false)
  expect(result.current.readerContext).toBeNull()
  expect(result.current.readerContextError).toBeNull()

  await act(async () => { await Promise.resolve() })
  expect(getReaderContext).not.toHaveBeenCalled()
})

it('reading boundaries alone enables the shared reader-context payload', async () => {
  const { result } = renderRatingView({ readerContextRequested: true, readingBoundariesRequested: true })

  await waitFor(() => expect(result.current.readerContext).not.toBeNull())
  expect(getReaderContext).toHaveBeenCalledWith(ACTIVE_THREAD.issue_id)
  expect(getReaderContext).toHaveBeenCalledTimes(1)
})

it('opening the second surface reuses the cached reader context instead of refetching', async () => {
  const { result, setScopes } = renderRatingView({
    readerContextRequested: true,
    readingBoundariesRequested: true,
  })
  await waitFor(() => expect(result.current.readerContext).not.toBeNull())
  expect(getReaderContext).toHaveBeenCalledTimes(1)

  setScopes({
    readerContextRequested: true,
    readingContextRequested: true,
    readingBoundariesRequested: true,
  })

  await act(async () => { await Promise.resolve() })
  expect(getReaderContext).toHaveBeenCalledTimes(1)
  expect(result.current.readerContext).not.toBeNull()
})

it('exposes both optional request scopes through the rating-view boundary', () => {
  const { result } = renderRatingView({
    readingContextRequested: true,
    readingBoundariesRequested: false,
  })

  expect(result.current.readingContextRequested).toBe(true)
  expect(result.current.readingBoundariesRequested).toBe(false)
})

it('exposes bounded optional loading and error state for the cards', () => {
  const readingOrdersError = new Error('reading orders unavailable')
  const connectedThreadsError = new Error('connected threads unavailable')

  const { result } = renderRatingView({
    readingContextRequested: true,
    readingOrdersIsLoading: true,
    readingOrdersError,
    connectedThreadsIsLoading: false,
    connectedThreadsError,
  })

  expect(result.current.readingOrdersIsLoading).toBe(true)
  expect(result.current.readingOrdersError).toBe(readingOrdersError)
  expect(result.current.connectedThreadsIsLoading).toBe(false)
  expect(result.current.connectedThreadsError).toBe(connectedThreadsError)
})

it('a failed reader-context request stays out of the shared rating error channel', async () => {
  getReaderContext.mockRejectedValue(new Error('reader context unavailable'))
  const setErrorMessage = vi.fn()
  const state = mockState({ activeRatingThread: ACTIVE_THREAD, setErrorMessage })

  const { result } = renderHook(
    () =>
      useRatingView({
        state,
        readerContextRequested: true,
        readingContextRequested: true,
        readingBoundariesRequested: false,
        readingOrders: [],
        connectedThreads: [],
        onShowContext: vi.fn(),
        onShowBoundaries: vi.fn(),
        readingOrdersIsLoading: false,
        readingOrdersError: new Error('reading orders unavailable'),
        connectedThreadsIsLoading: false,
        connectedThreadsError: new Error('connected threads unavailable'),
        rating,
        snooze,
        onSkip: vi.fn(),
        rateMutation,
        snoozeMutation,
        dismissPendingMutation,
        skipMutation,
        ratingViewTopRef,
      }),
    { wrapper: createWrapper() },
  )

  await waitFor(() => expect(result.current.readerContextError).not.toBeNull())
  expect(result.current.readerContextError?.message).toBe('reader context unavailable')

  // Optional failures are available to the cards but never promoted into the
  // page-level rating errorMessage used by Save/Snooze/Skip/Cancel.
  expect(result.current.errorMessage).toBe('')
  expect(setErrorMessage).not.toHaveBeenCalled()
  expect(result.current.rateIsPending).toBe(false)
  expect(result.current.dismissIsPending).toBe(false)
})
