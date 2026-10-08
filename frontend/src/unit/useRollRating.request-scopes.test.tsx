import { act, renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, expect, it, vi } from 'vitest'
import { useRollRating } from '../pages/RollPage/useRollRating'
import { readingOrdersApi } from '../services/api-reading-orders'
import { dependenciesApi } from '../services/api-dependencies'
import type { RollPageState, RollPageStateSetters } from '../pages/RollPage/useRollPageState'
import type { RatingThread, ThreadMetadata } from '../pages/RollPage/types'

vi.mock('../services/api-reading-orders', () => ({
  readingOrdersApi: { getForThread: vi.fn() },
}))
vi.mock('../services/api-dependencies', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/api-dependencies')>()
  return {
    ...actual,
    dependenciesApi: { getConnectedThreads: vi.fn() },
  }
})

const getForThread = vi.mocked(readingOrdersApi.getForThread)
const getConnectedThreads = vi.mocked(dependenciesApi.getConnectedThreads)

const ACTIVE_THREAD: RatingThread = {
  id: 1,
  title: 'Saga',
  format: 'Comic',
  issues_remaining: 5,
  total_issues: 10,
  queue_position: 0,
  issue_id: 100,
}

const THREAD_METADATA: ThreadMetadata = {
  title: 'Test Thread',
  id: 1,
  thread_id: 1,
  format: 'comic',
  issues_remaining: 5,
  queue_position: 1,
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

const mockRateMutation = { mutate: vi.fn().mockResolvedValue(undefined), isPending: false }
const mockDismissPendingMutation = { mutate: vi.fn().mockResolvedValue(undefined), isPending: false }
const mockRefetchBootstrap = vi.fn().mockResolvedValue(undefined)

function renderUseRollRating(
  stateOverrides: Partial<RollPageState & RollPageStateSetters> = {},
) {
  const state = mockState({ activeRatingThread: ACTIVE_THREAD, ...stateOverrides })
  const { result } = renderHook(
    () => useRollRating({ state, bootstrap: null, rateMutation: mockRateMutation, dismissPendingMutation: mockDismissPendingMutation, refetchBootstrap: mockRefetchBootstrap }),
    { wrapper: createWrapper() },
  )
  return { result, state }
}

beforeEach(() => {
  getForThread.mockReset()
  getConnectedThreads.mockReset()
  getForThread.mockResolvedValue({ reading_orders: [] })
  getConnectedThreads.mockResolvedValue({ thread_id: ACTIVE_THREAD.id, connected_threads: [] })
})

it('fresh rating entry triggers none of reader context, reading orders, or connected threads', async () => {
  const { result } = renderUseRollRating()

  expect(result.current.readerContextRequested).toBe(false)
  expect(result.current.readingContextRequested).toBe(false)
  expect(result.current.readingBoundariesRequested).toBe(false)

  // Let any effect/query scheduling settle before asserting the network stayed quiet.
  await act(async () => { await Promise.resolve() })
  expect(getForThread).not.toHaveBeenCalled()
  expect(getConnectedThreads).not.toHaveBeenCalled()
})

it('requesting Reading Context fetches reading orders and connected threads exactly once', async () => {
  const { result } = renderUseRollRating()

  act(() => { result.current.fetchReadingContext(ACTIVE_THREAD.id) })

  expect(result.current.readingContextRequested).toBe(true)
  expect(result.current.readingBoundariesRequested).toBe(false)
  expect(result.current.readerContextRequested).toBe(true)

  await waitFor(() => expect(getForThread).toHaveBeenCalledWith(ACTIVE_THREAD.id))
  await waitFor(() => expect(getConnectedThreads).toHaveBeenCalledWith(ACTIVE_THREAD.id))
  expect(getForThread).toHaveBeenCalledTimes(1)
  expect(getConnectedThreads).toHaveBeenCalledTimes(1)
})

it('requesting Reading Boundaries alone fetches no reading orders and no connected threads', async () => {
  const { result } = renderUseRollRating()

  act(() => { result.current.fetchReadingBoundaries() })

  expect(result.current.readingBoundariesRequested).toBe(true)
  expect(result.current.readingContextRequested).toBe(false)
  expect(result.current.readerContextRequested).toBe(true)

  await act(async () => { await Promise.resolve() })
  expect(getForThread).not.toHaveBeenCalled()
  expect(getConnectedThreads).not.toHaveBeenCalled()
})

it('requesting one surface does not mark the other surface requested', async () => {
  const { result } = renderUseRollRating()

  act(() => { result.current.fetchReadingContext(ACTIVE_THREAD.id) })
  expect(result.current.readingBoundariesRequested).toBe(false)

  act(() => { result.current.fetchReadingBoundaries() })
  expect(result.current.readingContextRequested).toBe(true)

  const second = renderUseRollRating()
  act(() => { second.result.current.fetchReadingBoundaries() })
  expect(second.result.current.readingContextRequested).toBe(false)
})

it('the shared reader-context flag stays false until a surface is requested', async () => {
  const { result } = renderUseRollRating()
  expect(result.current.readerContextRequested).toBe(false)

  act(() => { result.current.fetchReadingContext(ACTIVE_THREAD.id) })
  expect(result.current.readerContextRequested).toBe(true)
})

it('request state and its fetches reset when entering a new rating view', async () => {
  const { result } = renderUseRollRating()

  act(() => { result.current.fetchReadingContext(ACTIVE_THREAD.id) })
  await waitFor(() => expect(getForThread).toHaveBeenCalledTimes(1))

  await act(async () => {
    await result.current.enterRatingView(ACTIVE_THREAD.id, null, THREAD_METADATA)
  })

  expect(result.current.readingContextRequested).toBe(false)
  expect(result.current.readingBoundariesRequested).toBe(false)
  expect(result.current.readerContextRequested).toBe(false)

  await act(async () => { await Promise.resolve() })
  expect(getForThread).toHaveBeenCalledTimes(1)
  expect(getConnectedThreads).toHaveBeenCalledTimes(1)
})

it('a failed reading-orders request stays local and leaves rating actions usable', async () => {
  getForThread.mockRejectedValue(new Error('reading orders unavailable'))
  const setErrorMessage = vi.fn()
  const { result } = renderUseRollRating({ setErrorMessage })

  act(() => { result.current.fetchReadingContext(ACTIVE_THREAD.id) })

  await waitFor(() => expect(result.current.readingOrdersIsError).toBe(true))
  expect(result.current.readingOrdersError?.message).toBe('reading orders unavailable')
  expect(result.current.readingOrdersIsLoading).toBe(false)
  expect(result.current.connectedThreadsError).toBeNull()

  // The failure stays on the optional surface and never reaches the shared
  // rating error channel used by Save/Snooze/Skip/Cancel.
  expect(setErrorMessage).not.toHaveBeenCalled()

  // Rating and completion actions remain callable after the optional failure.
  await act(async () => { await result.current.handleSubmitRating(false) })
  await act(async () => { await result.current.handleCancelRating() })
  expect(mockRateMutation.mutate).toHaveBeenCalled()
  expect(mockDismissPendingMutation.mutate).toHaveBeenCalled()
  // Those actions only ever clear the channel; the optional failure never wrote to it.
  for (const call of setErrorMessage.mock.calls) {
    expect(call[0]).not.toContain('reading orders')
  }
})

it('a failed connected-threads request stays local', async () => {
  getConnectedThreads.mockRejectedValue(new Error('connected threads unavailable'))
  const { result } = renderUseRollRating()

  act(() => { result.current.fetchReadingContext(ACTIVE_THREAD.id) })

  await waitFor(() => expect(result.current.connectedThreadsIsError).toBe(true))
  expect(result.current.connectedThreadsError?.message).toBe('connected threads unavailable')
  expect(result.current.connectedThreadsIsLoading).toBe(false)
  expect(result.current.readingOrdersError).toBeNull()
})

it('optional reading-detail state is not requested before the user asks for it', () => {
  const { result } = renderUseRollRating()

  expect(result.current.readingOrdersIsLoading).toBe(false)
  expect(result.current.connectedThreadsIsLoading).toBe(false)
  expect(result.current.readingOrdersIsError).toBe(false)
  expect(result.current.connectedThreadsIsError).toBe(false)
})
