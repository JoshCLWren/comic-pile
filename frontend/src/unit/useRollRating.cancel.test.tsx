import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useRollRating } from '../pages/RollPage/useRollRating'
import type { RollPageState, RollPageStateSetters } from '../pages/RollPage/useRollPageState'
import type { RatingThread } from '../pages/RollPage/types'

vi.mock('../hooks/useReaderContext', () => ({
  useReadingOrdersForThread: () => ({
    readingOrders: [], isPending: false, isError: false, error: null,
  }),
  useConnectedThreads: () => ({
    connectedThreads: [], isPending: false, isError: false, error: null,
  }),
}))

const ACTIVE: RatingThread = {
  id: 7,
  title: 'Series',
  format: 'Comic',
  issues_remaining: 3,
  total_issues: 10,
  queue_position: 1,
  issue_id: 100,
  issue_number: '12',
}

function state(): RollPageState & RollPageStateSetters {
  return {
    isRolling: false,
    rolledResult: 6,
    selectedThreadId: 7,
    isOverrideOpen: false,
    overrideThreadId: '',
    overrideErrorMessage: '',
    snoozedExpanded: false,
    isDieModalOpen: false,
    isSetCurrentIssueOpen: false,
    selectedThread: null,
    isActionSheetOpen: false,
    isDirectReadOpen: false,
    activeRatingThread: ACTIVE,
    showMigrationDialog: false,
    threadToMigrate: null,
    showSimpleMigration: false,
    isRatingView: true,
    isShuffleOpen: false,
    shuffleError: '',
    rating: 4,
    errorMessage: '',
    suppressPendingAutoOpenRef: { current: false },
    rollIntervalRef: { current: null },
    rollTimeoutRef: { current: null },
    setIsRolling: vi.fn(),
    setRolledResult: vi.fn(),
    setSelectedThreadId: vi.fn(),
    setIsOverrideOpen: vi.fn(),
    setOverrideThreadId: vi.fn(),
    setOverrideErrorMessage: vi.fn(),
    setSnoozedExpanded: vi.fn(),
    setIsDieModalOpen: vi.fn(),
    setIsSetCurrentIssueOpen: vi.fn(),
    setSelectedThread: vi.fn(),
    setIsActionSheetOpen: vi.fn(),
    setIsDirectReadOpen: vi.fn(),
    setActiveRatingThread: vi.fn(),
    setShowMigrationDialog: vi.fn(),
    setThreadToMigrate: vi.fn(),
    setShowSimpleMigration: vi.fn(),
    setIsRatingView: vi.fn(),
    setIsShuffleOpen: vi.fn(),
    setShuffleError: vi.fn(),
    setRating: vi.fn(),
    setErrorMessage: vi.fn(),
  }
}

describe('rating exit without server-owned pending', () => {
  const rateMutation = { mutate: vi.fn(), isPending: false }
  const dismissPendingMutation = { mutate: vi.fn(), isPending: false }
  const refetchBootstrap = vi.fn()
  const clearPending = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
    rateMutation.mutate.mockResolvedValue({ rate: undefined, bootstrap: null })
    dismissPendingMutation.mutate.mockResolvedValue(undefined)
    refetchBootstrap.mockResolvedValue(undefined)
  })

  function render() {
    return renderHook(() => useRollRating({
      state: state(),
      bootstrap: null,
      rateMutation,
      dismissPendingMutation,
      refetchBootstrap,
      clearPending,
    }))
  }

  it('cancels by clearing browser selection with no dismiss or bootstrap call', async () => {
    const { result } = render()
    await act(async () => { await result.current.handleCancelRating() })
    expect(clearPending).toHaveBeenCalledWith()
    expect(dismissPendingMutation.mutate).not.toHaveBeenCalled()
    expect(refetchBootstrap).not.toHaveBeenCalled()
  })

  it('clears the exact selected issue only after a successful rate', async () => {
    const { result } = render()
    await act(async () => { await result.current.handleSubmitRating() })
    expect(clearPending).toHaveBeenCalledWith(100)
  })
})
