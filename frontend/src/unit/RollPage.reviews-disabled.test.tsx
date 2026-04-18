import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import RollPage from '../pages/RollPage'
import { useSession } from '../hooks/useSession'
import { useStaleThreads, useThreads } from '../hooks/useThread'
import {
  useClearManualDie,
  useDismissPending,
  useOverrideRoll,
  useRoll,
  useSetDie,
} from '../hooks/useRoll'
import { useSnooze, useUnsnooze } from '../hooks/useSnooze'
import { useMoveToBack, useMoveToFront } from '../hooks/useQueue'
import { useRate } from '../hooks'
import { useCollections } from '../contexts/CollectionContext'
import { ToastProvider } from '../contexts/ToastContext'
import { threadsApi } from '../services/api'

const navigateSpy = vi.fn()
const reviewsApiMock = vi.hoisted(() => ({
  createOrUpdateReview: vi.fn(),
}))

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return {
    ...actual,
    useNavigate: () => navigateSpy,
  }
})

vi.mock('../components/LazyDice3D', () => ({
  default: ({ sides, value }: { sides: number; value: number }) => (
    <div data-testid="lazy-dice" data-sides={String(sides)} data-value={String(value)} />
  ),
}))

vi.mock('../config/featureFlags', () => ({
  isReviewsFeatureEnabled: vi.fn(() => false),
}))

vi.mock('../hooks/useSession', () => ({ useSession: vi.fn() }))
vi.mock('../hooks/useThread', () => ({ useThreads: vi.fn(), useStaleThreads: vi.fn() }))
vi.mock('../hooks/useRoll', () => ({
  useSetDie: vi.fn(),
  useClearManualDie: vi.fn(),
  useRoll: vi.fn(),
  useOverrideRoll: vi.fn(),
  useDismissPending: vi.fn(),
}))
vi.mock('../hooks/useSnooze', () => ({
  useSnooze: vi.fn(),
  useUnsnooze: vi.fn(),
}))
vi.mock('../hooks/useQueue', () => ({
  useMoveToFront: vi.fn(),
  useMoveToBack: vi.fn(),
}))
vi.mock('../hooks', async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>
  return {
    ...actual,
    useRate: vi.fn(),
  }
})
vi.mock('../contexts/CollectionContext', () => ({ useCollections: vi.fn() }))
vi.mock('../contexts/ToastContext', () => ({
  useToast: vi.fn(() => ({ showToast: vi.fn(), removeToast: vi.fn(), toasts: [] })),
  ToastProvider: ({ children }: { children: React.ReactNode }) => children,
}))
vi.mock('../services/api-reviews', () => ({
  reviewsApi: reviewsApiMock,
}))

const mockedUseSession = vi.mocked(useSession) as any
const mockedUseThreads = vi.mocked(useThreads) as any
const mockedUseStaleThreads = vi.mocked(useStaleThreads) as any
const mockedUseSetDie = vi.mocked(useSetDie) as any
const mockedUseClearManualDie = vi.mocked(useClearManualDie) as any
const mockedUseRoll = vi.mocked(useRoll) as any
const mockedUseOverrideRoll = vi.mocked(useOverrideRoll) as any
const mockedUseDismissPending = vi.mocked(useDismissPending) as any
const mockedUseSnooze = vi.mocked(useSnooze) as any
const mockedUseUnsnooze = vi.mocked(useUnsnooze) as any
const mockedUseMoveToFront = vi.mocked(useMoveToFront) as any
const mockedUseMoveToBack = vi.mocked(useMoveToBack) as any
const mockedUseRate = vi.mocked(useRate) as any
const mockedUseCollections = vi.mocked(useCollections) as any

const baseRollResponse = {
  thread_id: 1,
  title: 'Saga',
  format: 'Comics',
  issues_remaining: 5,
  queue_position: 1,
  die_size: 6,
  result: 3,
  offset: 0,
  snoozed_count: 0,
  issue_id: null,
  issue_number: null,
  next_issue_id: null,
  next_issue_number: null,
  total_issues: 50,
  reading_progress: null,
}

function getPoolItem(title: string): HTMLElement {
  const element = screen.getByText(title).closest('[role="button"]')
  if (!(element instanceof HTMLElement)) {
    throw new Error(`Pool item for ${title} not found`)
  }
  return element
}

beforeEach(() => {
  navigateSpy.mockReset()
  reviewsApiMock.createOrUpdateReview.mockReset()
  vi.spyOn(threadsApi, 'setPending').mockResolvedValue(baseRollResponse)
  mockedUseSession.mockReturnValue({
    data: {
      current_die: 6,
      last_rolled_result: null,
      manual_die: null,
      has_restore_point: false,
      snoozed_threads: [],
    },
    refetch: vi.fn().mockResolvedValue(undefined),
  })
  mockedUseThreads.mockReturnValue({
    data: [
      { id: 1, title: 'Saga', format: 'Comics', status: 'active' },
      { id: 2, title: 'X-Men', format: 'Comics', status: 'active' },
    ],
    refetch: vi.fn().mockResolvedValue(undefined),
  })
  mockedUseStaleThreads.mockReturnValue({ data: [] })
  mockedUseSetDie.mockReturnValue({ mutate: vi.fn(), isPending: false })
  mockedUseClearManualDie.mockReturnValue({ mutate: vi.fn(), isPending: false })
  mockedUseRoll.mockReturnValue({ mutate: vi.fn().mockResolvedValue(baseRollResponse), isPending: false })
  mockedUseOverrideRoll.mockReturnValue({ mutate: vi.fn(), isPending: false })
  mockedUseDismissPending.mockReturnValue({ mutate: vi.fn(), isPending: false })
  mockedUseSnooze.mockReturnValue({ mutate: vi.fn(), isPending: false })
  mockedUseUnsnooze.mockReturnValue({ mutate: vi.fn(), isPending: false })
  mockedUseMoveToFront.mockReturnValue({ mutate: vi.fn(), isPending: false })
  mockedUseMoveToBack.mockReturnValue({ mutate: vi.fn(), isPending: false })
  mockedUseRate.mockReturnValue({ mutate: vi.fn().mockResolvedValue(undefined), isPending: false })
  mockedUseCollections.mockReturnValue({
    collections: [],
    activeCollectionId: null,
    setActiveCollectionId: vi.fn(),
    isLoading: false,
  })
})

afterEach(() => {
  vi.restoreAllMocks()
})

it('submits the rating immediately without showing review UI when reviews are disabled', async () => {
  const user = userEvent.setup()
  render(
    <ToastProvider>
      <RollPage />
    </ToastProvider>,
  )

  await user.click(getPoolItem('Saga'))
  await user.click(screen.getByText('Read Now'))
  await user.click(screen.getByText('Save & Continue'))

  await waitFor(() => {
    expect(screen.getByText('Tap Die to Roll')).toBeInTheDocument()
  })

  expect(screen.queryByText('Write a Review?')).not.toBeInTheDocument()
  expect(reviewsApiMock.createOrUpdateReview).not.toHaveBeenCalled()
})
