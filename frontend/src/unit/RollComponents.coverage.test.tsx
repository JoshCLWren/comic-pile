import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import type { RatingViewData } from '../pages/RollPage/useRatingView'
vi.mock('../contexts/useToast', () => ({ useToast: () => ({ toasts: [], showToast: vi.fn(), removeToast: vi.fn() }) }))
import { ThreadPool } from '../pages/RollPage/components/ThreadPool'
import { RatingView } from '../pages/RollPage/components/RatingView'
import type { Thread } from '../types'

vi.mock('../components/LazyDice3D', () => ({ default: () => <div data-testid="dice" /> }))
vi.mock('../contexts/useToast', () => ({
  useToast: () => ({ showToast: vi.fn(), removeToast: vi.fn(), toasts: [] }),
}))
vi.mock('../components/Tooltip', () => ({ default: ({ children }: { children: React.ReactNode }) => <>{children}</> }))
vi.mock('../components/IssueCorrectionDialog', () => ({ default: ({ isOpen, onClose, onSuccess }: { isOpen: boolean; onClose: () => void; onSuccess: () => void }) => isOpen ? <><button onClick={onClose}>Close correction</button><button onClick={onSuccess}>Correct successfully</button></> : null }))
vi.mock('../hooks/useRollBootstrap', () => ({
  useRollBootstrap: () => ({ data: null, isPending: false, isError: false, error: null }),
}))
vi.mock('../hooks/useReaderContext', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../hooks/useReaderContext')>()
  return {
    ...actual,
    useReaderContext: () => ({
      context: null,
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    }),
  }
})

const thread: Thread = {
  id: 1,
  title: 'Saga',
  format: 'Comic',
  issues_remaining: 5,
  total_issues: 10,
  next_unread_issue_number: '3',
  queue_position: 1,
  status: 'active',
  is_blocked: false,
  blocking_reasons: [],
  last_activity_at: null,
  last_rating: null,
  notes: null,
  is_test: false,
  created_at: '2000-01-01T00:00:00Z',
}
const callbacks = () => ({
  onThreadClick: vi.fn(), onUnsnooze: vi.fn(), onUnskip: vi.fn(), onReadStale: vi.fn(), onToggleSnoozed: vi.fn(),
  onToggleSkipped: vi.fn(), onToggleStale: vi.fn(), onToggleBlocked: vi.fn(), onShuffle: vi.fn(),
})

type ThreadPoolProps = Parameters<typeof ThreadPool>[0]

describe('ThreadPool diagnostic removal (#4441)', () => {
  it('renders the empty state and retains available issue controls', async () => {
    const actions = callbacks()
    const { rerender } = render(
      <MemoryRouter><ThreadPool pool={[]} blockedThreads={[]} blockingDependencyMap={{}} isRatingView={false} selectedThreadId={null} staleThread={null} staleThreadCount={0} snoozedThreads={[]} snoozedExpanded={false} skippedThreads={[]} skippedExpanded={false} blockedExpanded={false} staleExpanded={false} unsnoozeIsPending={false} unskipIsPending={false} shuffleIsPending={false} {...actions} /></MemoryRouter>,
    )
    expect(screen.getByText('Nothing to roll yet')).toBeInTheDocument()
    await userEvent.setup().click(screen.getByRole('button', { name: /add a series/i }))
    rerender(
      <MemoryRouter><ThreadPool pool={[thread]} blockedThreads={[{ ...thread, id: 2, title: 'Blocked' }]} blockingDependencyMap={{}} isRatingView={false} selectedThreadId={null} staleThread={null} staleThreadCount={0} snoozedThreads={[]} snoozedExpanded={false} skippedThreads={[]} skippedExpanded={false} blockedExpanded={true} staleExpanded={true} inactiveThreads={[{ thread_id: 4, title: 'Inactive', format: 'Comic', reason: 'completed' }]} inactiveExpanded={true} unsnoozeIsPending={false} unskipIsPending={false} shuffleIsPending={false} {...actions} /></MemoryRouter>,
    )
    expect(screen.queryByText('Blocked')).not.toBeInTheDocument()
    expect(screen.queryByText('Inactive')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Die face 1: Saga/i })).toBeInTheDocument()
    await userEvent.setup().click(screen.getByRole('button', { name: /Die face 1: Saga/i }))
    expect(actions.onThreadClick).toHaveBeenCalledWith(thread)
  })

  it('keeps snooze and skip controls without retired reports', async () => {
    const actions = callbacks()
    render(<MemoryRouter><ThreadPool pool={[]} blockedThreads={[]} blockingDependencyMap={{}} isRatingView={false} selectedThreadId={null} staleThread={null} staleThreadCount={0} snoozedThreads={[{id:3,title:'Snoozed',format:'Comic'}]} snoozedExpanded={true} skippedThreads={[{id:4,title:'Skipped',format:'Comic'}]} skippedExpanded={true} blockedExpanded={true} staleExpanded={true} unsnoozeIsPending={false} unskipIsPending={false} shuffleIsPending={false} {...actions} /></MemoryRouter>)
    expect(screen.getByText('Every series is snoozed')).toBeInTheDocument()
    await userEvent.setup().click(screen.getByRole('button', { name: 'Unsnooze this comic' }))
    expect(actions.onUnsnooze).toHaveBeenCalledWith(3)
    await userEvent.setup().click(screen.getByRole('button', { name: 'Unskip this comic' }))
    expect(actions.onUnskip).toHaveBeenCalledWith(4)
    expect(screen.queryByText(/waiting for earlier issues/i)).not.toBeInTheDocument()
  })
})

describe('RatingView', () => {
  function makeData(overrides: Partial<RatingViewData> = {}): RatingViewData {
    return {
      activeRatingThread: { id: 1, title: 'Saga', format: 'Comic', issues_remaining: 5, total_issues: 10, issue_number: '3', next_issue_number: '4', reading_progress: 'in_progress', queue_position: 0, issue_id: 100, next_issue_id: 101 },
      currentDie: 6, rolledResult: 3, rating: 3.0, predictedDie: 8, errorMessage: '', rateIsPending: false, rerollIsPending: false, dismissIsPending: false, skipIsPending: false, manualDie: null, onUpdateRating: vi.fn(), onSubmitRating: vi.fn(), onReroll: vi.fn().mockResolvedValue(undefined), onCancel: vi.fn(), onRefreshThread: vi.fn(), readerContext: null, isReaderContextLoading: false, readerContextError: null, ratingViewTopRef: null, issuesRemaining: 5, readingContextRequested: false, readingBoundariesRequested: false, readingOrders: [], connectedThreads: [], onShowContext: vi.fn(), onShowBoundaries: vi.fn(), readingOrdersIsLoading: false, readingOrdersError: null, connectedThreadsIsLoading: false, connectedThreadsError: null, ...overrides,
    }
  }

  it('renders rating states and invokes controls', async () => {
    const onUpdateRating = vi.fn(); const onSubmitRating = vi.fn(); const onReroll = vi.fn().mockResolvedValue(undefined); const onCancel = vi.fn(); const onRefreshThread = vi.fn()
    const user = userEvent.setup()
    render(<MemoryRouter><RatingView data={makeData({ rating: 5, onUpdateRating, onSubmitRating, onReroll, onCancel, onRefreshThread })} /></MemoryRouter>)
    expect(screen.getAllByText(/Saga/).length).toBeGreaterThan(0)
    expect(screen.queryByText('Why this?')).not.toBeInTheDocument()
    expect(screen.getByTestId('reading-context-button')).toBeInTheDocument()
    expect(screen.getByTestId('reading-boundaries-button')).toBeInTheDocument()
    expect(screen.getByTestId('rating-region-reading-optional')).toBeInTheDocument()
    // #3008: the correction action lives in the overflow menu.
    await user.click(screen.getByRole('button', { name: 'Comic corrections' }))
    await user.click(screen.getByRole('menuitem', { name: /fix issue number/i }))
    await user.click(screen.getByRole('button', { name: /close correction/i }))
    const rating = screen.getByRole('slider')
    fireEvent.change(rating, { target: { value: '3' } })
    expect(onUpdateRating).toHaveBeenCalledWith('3')
    await user.click(screen.getByRole('button', { name: /mark read & save/i }))
    await user.click(screen.getByRole('button', { name: /roll again/i }))
    expect(onSubmitRating).toHaveBeenCalled()
    expect(onReroll).toHaveBeenCalled()
  })

  it('renders empty, low-rating, progress, reading-order, and correction states', async () => {
    const callbacks = { onUpdateRating: vi.fn(), onSubmitRating: vi.fn(), onReroll: vi.fn().mockResolvedValue(undefined), onCancel: vi.fn(), onRefreshThread: vi.fn() }
    render(<MemoryRouter><RatingView data={makeData({ activeRatingThread: { id: 1, title: 'Saga', format: 'Comic', issues_remaining: 1, total_issues: 10, issue_number: '2', next_issue_number: null, reading_progress: 'completed', queue_position: 0, issue_id: 100, next_issue_id: null }, rating: 1, errorMessage: 'Oops', rerollIsPending: true, onUpdateRating: callbacks.onUpdateRating, onSubmitRating: callbacks.onSubmitRating, onReroll: callbacks.onReroll, onCancel: callbacks.onCancel, onRefreshThread: callbacks.onRefreshThread })} /></MemoryRouter>)
    expect(screen.getByText(/This is the last issue/)).toBeInTheDocument()
    expect(screen.getByText('Oops')).toBeInTheDocument()
    expect(screen.queryByText('Why this?')).not.toBeInTheDocument()
    expect(screen.getByTestId('reading-context-button')).toBeInTheDocument()
    expect(screen.getByTestId('reading-boundaries-button')).toBeInTheDocument()
    // #3008: the correction action lives in the overflow menu.
    await userEvent.setup().click(screen.getByRole('button', { name: 'Comic corrections' }))
    await userEvent.setup().click(screen.getByRole('menuitem', { name: /fix issue number/i }))
    await userEvent.setup().click(screen.getByRole('button', { name: 'Correct successfully' }))
    expect(callbacks.onRefreshThread).toHaveBeenCalled()
    fireEvent.change(screen.getByRole('slider'), { target: { value: '2' } })
    await userEvent.setup().click(screen.getByRole('button', { name: 'Rolling…' }))
    await userEvent.setup().click(screen.getByRole('button', { name: 'Cancel roll' }))
  })

  it('renders safe fallbacks for missing thread metadata', async () => {
    render(<MemoryRouter><RatingView data={makeData({ activeRatingThread: { id: 1, title: 'Saga', format: 'Comic', issues_remaining: 1, total_issues: 10, issue_number: '2', next_issue_number: null, reading_progress: null, queue_position: 0, issue_id: 100, next_issue_id: null }, onUpdateRating: vi.fn(), onSubmitRating: vi.fn(), onReroll: vi.fn().mockResolvedValue(undefined), onCancel: vi.fn(), onRefreshThread: vi.fn() })} /></MemoryRouter>)
    expect(screen.getByText('Saga')).toBeInTheDocument()
    expect(screen.queryByText('Why this?')).not.toBeInTheDocument()
    expect(screen.getByTestId('reading-context-button')).toBeInTheDocument()
    expect(screen.getByTestId('reading-boundaries-button')).toBeInTheDocument()
    expect(screen.getByTestId('rating-region-reading-optional')).toBeInTheDocument()
  })

  it('renders alternate rating, progress, and order boundaries', async () => {
    const callbacks = { onUpdateRating: vi.fn(), onSubmitRating: vi.fn(), onReroll: vi.fn().mockResolvedValue(undefined), onCancel: vi.fn(), onRefreshThread: vi.fn() }
    render(<MemoryRouter><RatingView data={makeData({ activeRatingThread: { id: 1, title: 'Saga', format: 'Comic', issues_remaining: 2, total_issues: 0, issue_number: null, next_issue_number: null, reading_progress: null, queue_position: 0, issue_id: 100, next_issue_id: null }, rating: 5, predictedDie: 6, rolledResult: 2, onUpdateRating: callbacks.onUpdateRating, onSubmitRating: callbacks.onSubmitRating, onReroll: callbacks.onReroll, onCancel: callbacks.onCancel, onRefreshThread: callbacks.onRefreshThread })} /></MemoryRouter>)
    expect(screen.getByText('Saga')).toBeInTheDocument()
    expect(screen.queryByText('Die stays the same')).not.toBeInTheDocument()
    expect(screen.getByTestId('reading-context-button')).toBeInTheDocument()
    expect(screen.getByTestId('rating-region-reading-optional')).toBeInTheDocument()
    await userEvent.setup().click(screen.getByRole('button', { name: 'Mark read & save' }))
    expect(callbacks.onSubmitRating).toHaveBeenCalledWith(false)
  })

  it('asserts Why this? stays absent while collapsed Reading Context and Reading Boundaries cards are present', async () => {
    render(<MemoryRouter><RatingView data={makeData({ activeRatingThread: { id: 1, title: 'Saga', format: 'Comic', issues_remaining: 1, total_issues: 10, issue_number: '2', next_issue_number: null, reading_progress: null, queue_position: 0, issue_id: 100, next_issue_id: null }, onUpdateRating: vi.fn(), onSubmitRating: vi.fn(), onReroll: vi.fn().mockResolvedValue(undefined), onCancel: vi.fn(), onRefreshThread: vi.fn() })} /></MemoryRouter>)
    expect(screen.queryByText('Why this?')).not.toBeInTheDocument()
    expect(screen.getByText('Reading Context (optional)')).toBeInTheDocument()
    expect(screen.getByText('Reading Boundaries (optional)')).toBeInTheDocument()
    expect(screen.getByTestId('reading-context-button')).toBeInTheDocument()
    expect(screen.getByTestId('reading-boundaries-button')).toBeInTheDocument()
    expect(screen.getByTestId('rating-region-reading-optional')).toBeInTheDocument()
    expect(screen.queryByTestId('rating-region-reading-context')).not.toBeInTheDocument()
    expect(screen.queryByTestId('rating-region-reading-boundaries')).not.toBeInTheDocument()
    expect(screen.getByTestId('rating-pillars-grid').className).not.toContain('xl:grid-cols-[repeat(auto-fit')
    expect(screen.getByTestId('rating-region-comic')).toBeInTheDocument()
    expect(screen.getByTestId('rating-region-decision')).toBeInTheDocument()
  })
})
