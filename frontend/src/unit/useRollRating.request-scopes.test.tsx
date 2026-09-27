import { act, renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { expect, it, vi } from 'vitest'
import { useRollRating } from '../pages/RollPage/useRollRating'
import type { RollPageState, RollPageStateSetters } from '../pages/RollPage/useRollPageState'

vi.mock('../services/api-reading-orders', () => ({
  readingOrdersApi: { getForThread: vi.fn().mockResolvedValue({ reading_orders: [] }) },
}))
vi.mock('../services/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/api')>()
  return {
    ...actual,
    dependenciesApi: { getConnectedThreads: vi.fn().mockResolvedValue({ connected_threads: [] }) },
  }
})
vi.mock('../services/api-reader-context', () => ({
  readerContextApi: { get: vi.fn() },
}))

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

function renderUseRollRating(stateOverrides = {}) {
  const state = mockState(stateOverrides)
  const { result } = renderHook(
    () => useRollRating({ state, bootstrap: null, rateMutation: mockRateMutation, dismissPendingMutation: mockDismissPendingMutation, refetchBootstrap: mockRefetchBootstrap }),
    { wrapper: createWrapper() },
  )
  return { result, state }
}

it('fresh rating entry triggers none of reader context, reading orders, or connected threads', () => {
  const { result } = renderUseRollRating()
  const { current } = result
  expect(current.readerContextRequested).toBe(false)
  expect(current.readingContextRequested).toBe(false)
  expect(current.readingBoundariesRequested).toBe(false)
})

it('requestReaderContext sets both readingContextRequested and readingBoundariesRequested', () => {
  const { result } = renderUseRollRating()
  act(() => {
    result.current.requestReaderContext()
  })
  expect(result.current.readingContextRequested).toBe(true)
  expect(result.current.readingBoundariesRequested).toBe(true)
  expect(result.current.readerContextRequested).toBe(true)
})

it('fetchReadingContext sets readingContextRequested but not readingBoundariesRequested', () => {
  const { result } = renderUseRollRating()
  act(() => {
    result.current.fetchReadingContext(1)
  })
  expect(result.current.readingContextRequested).toBe(true)
  expect(result.current.readingBoundariesRequested).toBe(false)
  expect(result.current.readerContextRequested).toBe(true)
})

it('fetchReadingBoundaries sets readingBoundariesRequested but not readingContextRequested', () => {
  const { result } = renderUseRollRating()
  act(() => {
    result.current.fetchReadingBoundaries()
  })
  expect(result.current.readingBoundariesRequested).toBe(true)
  expect(result.current.readingContextRequested).toBe(false)
  expect(result.current.readerContextRequested).toBe(true)
})

it('reading orders and connected threads are only enabled when readingContextRequested is true', async () => {
  const { result } = renderUseRollRating()
  act(() => {
    result.current.fetchReadingContext(1)
  })
  await waitFor(() => expect(result.current.readingContextRequested).toBe(true))
})

it('reading boundaries alone does not enable reading orders or connected threads', async () => {
  const { result } = renderUseRollRating()
  act(() => {
    result.current.fetchReadingBoundaries()
  })
  expect(result.current.readingContextRequested).toBe(false)
})

it('request state resets when entering a new rating view', async () => {
  const { result } = renderUseRollRating()
  act(() => {
    result.current.fetchReadingContext(1)
    result.current.fetchReadingBoundaries()
  })
  expect(result.current.readingContextRequested).toBe(true)
  expect(result.current.readingBoundariesRequested).toBe(true)

  await act(async () => {
    await result.current.enterRatingView(1, null, { title: 'Test Thread', id: 1, thread_id: 1, format: 'comic', issues_remaining: 5, queue_position: 1 })
  })
  expect(result.current.readingContextRequested).toBe(false)
  expect(result.current.readingBoundariesRequested).toBe(false)
})

it('optional-data failures do not populate the global errorMessage', () => {
  const setErrorMessage = vi.fn()
  const state = mockState({ setErrorMessage })
  renderHook(
    () => useRollRating({ state, bootstrap: null, rateMutation: mockRateMutation, dismissPendingMutation: mockDismissPendingMutation, refetchBootstrap: mockRefetchBootstrap }),
    { wrapper: createWrapper() },
  )
  expect(setErrorMessage).not.toHaveBeenCalled()
})

it('readerContextRequested is derived as readingContextRequested || readingBoundariesRequested', () => {
  const { result } = renderUseRollRating()
  expect(result.current.readerContextRequested).toBe(false)

  act(() => { result.current.fetchReadingContext(1) })
  expect(result.current.readerContextRequested).toBe(true)

  act(() => { result.current.fetchReadingBoundaries() })
  expect(result.current.readerContextRequested).toBe(true)
})

it('fetchReadingDetails sets both readingContextRequested and readingBoundariesRequested', () => {
  const { result } = renderUseRollRating()
  act(() => {
    result.current.fetchReadingDetails(1)
  })
  expect(result.current.readingContextRequested).toBe(true)
  expect(result.current.readingBoundariesRequested).toBe(true)
  expect(result.current.readerContextRequested).toBe(true)
})
