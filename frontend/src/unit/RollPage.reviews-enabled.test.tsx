import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import RollPage from '../pages/RollPage'

const mocks = vi.hoisted(() => ({
  mutate: vi.fn().mockResolvedValue(undefined),
  setPending: vi.fn().mockResolvedValue({
    thread_id: 1, title: 'Saga', format: 'Comic', issues_remaining: 2,
    queue_position: 1, total_issues: 10, result: 4,
  }),
  createReview: vi.fn().mockResolvedValue({}),
  refetch: vi.fn().mockResolvedValue({}),
}))
const restore = vi.hoisted(() => ({ action: null as (() => void) | null }))
const sessionData = { current_die: 6, snoozed_threads: [] as Array<{ id: number }> }
const threadData = [{ id: 1, title: 'Saga', format: 'Comic', status: 'active' as const, queue_position: 1 }]

vi.mock('react-router-dom', () => ({ useNavigate: () => vi.fn() }))
vi.mock('../config/featureFlags', () => ({ collectionsEnabled: true, isReviewsFeatureEnabled: () => true }))
vi.mock('../contexts/CollectionContext', () => ({ useCollections: () => ({
  collections: [], activeCollectionId: null, setActiveCollectionId: vi.fn(), isLoading: false, error: null,
}) }))
vi.mock('../contexts/useBugReportRestore', () => ({
  useBugReportRestore: () => ({
    setRestoreAction: vi.fn((action: () => void) => { restore.action = action }),
    clearRestoreAction: vi.fn(),
  }),
}))
vi.mock('../hooks/useSession', () => ({ useSession: () => ({ data: sessionData, refetch: mocks.refetch }) }))
vi.mock('../hooks/useThread', () => ({
  useThreads: () => ({ data: threadData, refetch: mocks.refetch }),
  useStaleThreads: () => ({ data: [], refetch: mocks.refetch }),
}))
vi.mock('../hooks/useRoll', () => ({
  useSetDie: () => ({ mutate: mocks.mutate, isPending: false }),
  useClearManualDie: () => ({ mutate: mocks.mutate, isPending: false }),
  useRoll: () => ({ mutate: mocks.mutate, isPending: false }),
  useDismissPending: () => ({ mutate: mocks.mutate, isPending: false }),
  useOverrideRoll: () => ({ mutate: mocks.mutate, isPending: false }),
}))
vi.mock('../hooks/useSnooze', () => ({ useSnooze: () => ({ mutate: mocks.mutate, isPending: false }), useUnsnooze: () => ({ mutate: mocks.mutate, isPending: false }) }))
vi.mock('../hooks/useQueue', () => ({ useMoveToFront: () => ({ mutate: mocks.mutate, isPending: false }), useMoveToBack: () => ({ mutate: mocks.mutate, isPending: false }), useShuffleQueue: () => ({ mutate: mocks.mutate, isPending: false }) }))
vi.mock('../hooks', () => ({ useRate: () => ({ mutate: mocks.mutate, isPending: false }) }))
vi.mock('../services/api', () => ({ threadsApi: { setPending: mocks.setPending }, dependenciesApi: { getConnectedThreads: vi.fn().mockResolvedValue({ connected_threads: [] }), getBlockingInfo: vi.fn().mockResolvedValue({ blocking_reasons: [] }) } }))
vi.mock('../services/api-reading-orders', () => ({ readingOrdersApi: { getForThread: vi.fn().mockResolvedValue({ reading_orders: [] }) } }))
vi.mock('../services/api-reviews', () => ({ reviewsApi: { createOrUpdateReview: mocks.createReview } }))
vi.mock('../components/LazyDice3D', () => ({ default: () => <div data-testid="dice" /> }))
vi.mock('../components/Tooltip', () => ({ default: ({ children }: { children: React.ReactNode }) => <>{children}</> }))
vi.mock('../components/Modal', () => ({ default: ({ isOpen, title, children, onClose }: { isOpen: boolean; title: string; children: React.ReactNode; onClose: () => void }) => isOpen ? <section><h2>{title}</h2><button onClick={onClose}>close modal</button>{children}</section> : null }))
vi.mock('../components/CollectionDialog', () => ({ default: ({ onClose }: { onClose: () => void }) => <button onClick={onClose}>close collection</button> }))
vi.mock('../components/MigrationDialog', () => ({ default: () => null }))
vi.mock('../components/SimpleMigrationDialog', () => ({ default: () => null }))
vi.mock('../components/ReviewForm', () => ({ default: ({ onSubmit, onClose, error, existingReview }: { onSubmit: (data: { review_text: string }) => void; onClose: () => void; error?: string | null; existingReview?: unknown }) => <div>{existingReview !== null && existingReview !== undefined && <span>existing review loaded</span>}<button onClick={() => onSubmit({ review_text: 'Great issue' })}>submit review</button><button onClick={onClose}>close review</button>{error && <span>{error}</span>}</div> }))
vi.mock('../pages/RollPage/components/ThreadPool', () => ({ ThreadPool: ({ onThreadClick }: { onThreadClick: (thread: unknown) => void }) => <button onClick={() => onThreadClick({ id: 1, title: 'Saga', format: 'Comic', status: 'active' })}>thread</button> }))
vi.mock('../pages/RollPage/components/RatingView', () => ({ RatingView: ({ onSubmitRating, onUpdateRating, onCancel, errorMessage }: { onSubmitRating: () => void; onUpdateRating: (value: string) => void; onCancel: () => void; errorMessage?: string }) => <div>{errorMessage && <span>{errorMessage}</span>}<button onClick={() => onUpdateRating('5')}>update</button><button onClick={onSubmitRating}>save rating</button><button onClick={onCancel}>cancel</button></div> }))

describe('RollPage with reviews enabled', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    restore.action = null
    mocks.mutate.mockResolvedValue(undefined)
    mocks.createReview.mockResolvedValue({})
    mocks.refetch.mockResolvedValue({})
    Object.defineProperty(window, 'localStorage', { configurable: true, value: { getItem: () => 'token' } })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ reviews: [] }) }))
  })

  it('opens review form and saves a rating and review', async () => {
    render(<RollPage />)
    fireEvent.click(screen.getByRole('button', { name: /create new collection/i }))
    restore.action?.()
    fireEvent.click(screen.getByRole('button', { name: 'close collection' }))
    fireEvent.click(screen.getByRole('button', { name: 'thread' }))
    fireEvent.click(screen.getByRole('button', { name: /Read Now/ }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'save rating' })).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'update' }))
    fireEvent.click(screen.getByRole('button', { name: 'save rating' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'submit review' })).toBeInTheDocument())
    restore.action?.()
    fireEvent.click(screen.getByRole('button', { name: 'submit review' }))
    await waitFor(() => expect(mocks.createReview).toHaveBeenCalled())
  })

  it('keeps the review form open when review persistence fails', async () => {
    mocks.createReview.mockRejectedValueOnce(new Error('review unavailable'))
    render(<RollPage />)
    fireEvent.click(screen.getByRole('button', { name: 'thread' }))
    fireEvent.click(screen.getByRole('button', { name: /Read Now/ }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'save rating' })).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'save rating' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'submit review' })).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'submit review' }))
    await waitFor(() => expect(screen.getByText(/review text failed/i)).toBeInTheDocument())
  })

  it('handles existing-review lookup misses, rating failures, and review cancellation', async () => {
    vi.mocked(fetch).mockResolvedValueOnce({ ok: false } as Response)
    mocks.mutate.mockRejectedValueOnce(new Error('rating failed'))
    render(<RollPage />)
    fireEvent.click(screen.getByRole('button', { name: 'thread' }))
    fireEvent.click(screen.getByRole('button', { name: /Read Now/ }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'save rating' })).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'save rating' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'submit review' })).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'submit review' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'submit review' })).toBeInTheDocument())
    mocks.mutate.mockResolvedValue(undefined)
    fireEvent.click(screen.getByRole('button', { name: 'close review' }))
    expect(screen.queryByRole('button', { name: 'submit review' })).not.toBeInTheDocument()
  })

  it('keeps rating usable when the existing-review lookup fails', async () => {
    vi.mocked(fetch).mockRejectedValueOnce(new Error('review lookup failed'))
    render(<RollPage />)
    fireEvent.click(screen.getByRole('button', { name: 'thread' }))
    fireEvent.click(screen.getByRole('button', { name: /Read Now/ }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'save rating' })).toBeInTheDocument())
    await waitFor(() => expect(screen.getByRole('button', { name: 'save rating' })).toBeInTheDocument())
  })

  it('loads an existing review for the selected thread and supports a missing token', async () => {
    vi.mocked(fetch).mockResolvedValueOnce({ ok: true, json: async () => ({ reviews: [{ thread_id: 1, issue_number: null, review_text: 'Old review' }] }) } as Response)
    render(<RollPage />)
    fireEvent.click(screen.getByRole('button', { name: 'thread' }))
    fireEvent.click(screen.getByRole('button', { name: /Read Now/ }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'save rating' })).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'save rating' }))
    await waitFor(() => expect(screen.getByText('existing review loaded')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'close review' }))

    Object.defineProperty(window, 'localStorage', { configurable: true, value: { getItem: () => null } })
    render(<RollPage />)
    fireEvent.click(screen.getAllByRole('button', { name: 'thread' }).at(-1)!)
    fireEvent.click(screen.getAllByRole('button', { name: /Read Now/ }).at(-1)!)
    await waitFor(() => expect(screen.getAllByRole('button', { name: 'save rating' }).length).toBeGreaterThan(0))
  })
})
