import { useState } from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { cast } from '../utils/cast'
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

// SAFETY: staleExpanded is controlled by RollPage state, so a static prop can never expand the
// section. This harness owns the same toggle state the real page owns, letting the test drive the
// collapse/expand interaction instead of asserting against a frozen prop.
function StaleSectionHarness(props: Omit<ThreadPoolProps, 'staleExpanded' | 'onToggleStale'>) {
  const [staleExpanded, setStaleExpanded] = useState(false)
  return (
    <MemoryRouter>
      <ThreadPool
        {...props}
        staleExpanded={staleExpanded}
        onToggleStale={() => setStaleExpanded((value) => !value)}
      />
    </MemoryRouter>
  )
}

describe('ThreadPool', () => {
  it('renders empty, blocked, pool, stale, and snoozed states', async () => {
    const empty = callbacks()
    const { rerender } = render(<MemoryRouter><ThreadPool pool={[]} blockedThreads={[]} blockingDependencyMap={{}} isRatingView={false} selectedThreadId={null} staleThread={null} staleThreadCount={0} snoozedThreads={[]} snoozedExpanded={false} skippedThreads={[]} skippedExpanded={false} blockedExpanded={false} staleExpanded={false} unsnoozeIsPending={false} unskipIsPending={false} shuffleIsPending={false} {...empty} /></MemoryRouter>)
    expect(screen.getByText('Nothing to roll yet')).toBeInTheDocument()
    await userEvent.setup().click(screen.getByRole('button', { name: /add a series/i }))
    expect(empty.onShuffle).not.toHaveBeenCalled()

    const actions = callbacks()
    // SAFETY: Test injects a synthetic staleThread with extra days field to cover the stale branch; the cast widens Thread to the stale shape the component reads.
    rerender(<MemoryRouter><ThreadPool pool={[]} blockedThreads={[{ ...thread, id: 2, title: 'Blocked' }]} blockingDependencyMap={{ 2: [{ thread_id: 9, thread_title: 'Saga', issue_number: '1', label: 'Read Saga first' }] }} isRatingView={false} selectedThreadId={null} staleThread={cast<Parameters<typeof ThreadPool>[0]['staleThread']>({ ...thread, days: 4 })} staleThreadCount={2} snoozedThreads={[{ id: 3, title: 'Snoozed', format: 'Comic' }]} snoozedExpanded={false} skippedThreads={[]} skippedExpanded={false} blockedExpanded={false} staleExpanded={false} unsnoozeIsPending={false} unskipIsPending={false} shuffleIsPending={false} {...actions} /></MemoryRouter>)
    expect(screen.getByText(/Every series is blocked or snoozed/)).toBeInTheDocument()
    await userEvent.setup().click(screen.getByRole('button', { name: /go to queue/i }))
    expect(actions.onToggleBlocked).not.toHaveBeenCalled()

    // SAFETY: Same synthetic staleThread widening for the second stale branch.
    rerender(<MemoryRouter><ThreadPool pool={[thread]} blockedThreads={[]} blockingDependencyMap={{}} isRatingView={false} selectedThreadId={1} staleThread={cast<Parameters<typeof ThreadPool>[0]['staleThread']>({ ...thread, days: 2 })} staleThreadCount={1} snoozedThreads={[{ id: 3, title: 'Snoozed', format: 'Comic' }]} snoozedExpanded={false} skippedThreads={[]} skippedExpanded={false} blockedExpanded={false} staleExpanded={false} unsnoozeIsPending={false} unskipIsPending={false} shuffleIsPending={false} {...actions} /></MemoryRouter>)
    await userEvent.setup().click(screen.getByRole('button', { name: /snoozed/i }))
    await userEvent.setup().click(screen.getAllByText('Saga')[0]!)
    expect(actions.onThreadClick).toHaveBeenCalledWith(thread)
    fireEvent.keyDown(screen.getAllByText('Saga')[0]!.closest('[role="button"]')!, { key: 'Enter' })
    expect(actions.onThreadClick).toHaveBeenCalledTimes(2)
  })

  it('covers expanded blocked, stale, snoozed, selected, rolling, and disabled controls', async () => {
    const actions = callbacks()
    // SAFETY: Synthetic stale thread with days field exercises the stale rendering branch; the type widens Thread to the stale shape.
    const stale = cast<Parameters<typeof ThreadPool>[0]['staleThread']>({ ...thread, title: 'Stale Saga', days: 9 })
    render(<StaleSectionHarness pool={[]} blockedThreads={[{ ...thread, id: 2, title: 'Blocked' }]} blockingDependencyMap={{ 2: [{ thread_id: 9, thread_title: 'Saga', issue_number: '1', label: 'Prerequisite' }] }} isRatingView={false} selectedThreadId={null} staleThread={stale} staleThreadCount={2} snoozedThreads={[{ id: 3, title: 'Snoozed', format: 'Comic' }]} snoozedExpanded={true} skippedThreads={[]} skippedExpanded={false} blockedExpanded={true} unsnoozeIsPending={false} unskipIsPending={false} shuffleIsPending={false} {...actions} />)
    await userEvent.setup().click(screen.getByRole('button', { name: /series waiting for earlier issues/i }))
    expect(screen.getByText('Prerequisite')).toBeInTheDocument()
    const hiddenBlockerLink = screen.getByRole('link', { name: 'Open Saga' })
    expect(hiddenBlockerLink).toHaveAttribute('href', '/thread/9')
    fireEvent.keyDown(screen.getByRole('button', { name: /series waiting for earlier issues/i }), { key: 'ArrowDown' })
    await userEvent.setup().click(screen.getByRole('button', { name: /Snoozed \(1\)/i }))
    await userEvent.setup().click(screen.getByRole('button', { name: 'Unsnooze this comic' }))
    expect(actions.onUnsnooze).toHaveBeenCalledWith(3)
    // SAFETY: The stale card is rendered once the stale section is expanded; toggle it open first so the roll button is reachable.
    await userEvent.setup().click(screen.getByRole('button', { name: /series you haven't opened recently/i }))
    const rollButton = screen.getByRole('button', { name: /roll this series now/i })
    await userEvent.setup().click(rollButton)
    expect(actions.onReadStale).toHaveBeenCalledWith(thread.id)
  })

  it('handles rating-view pool layout and pending controls', async () => {
    const actions = callbacks()
    const second = { ...thread, id: 4, title: 'Second' }
    // SAFETY: Minimal staleThread fixture with synthetic days field covers the rating-view pool branch.
    render(<MemoryRouter><ThreadPool
      pool={[thread, second]}
      blockedThreads={[{ ...thread, id: 5, title: 'Blocked without a reason' }]}
      blockingDependencyMap={{}}
      isRatingView
      selectedThreadId={null}
      staleThread={cast<Parameters<typeof ThreadPool>[0]['staleThread']>({ ...thread, days: 1 })}
      staleThreadCount={1}
      snoozedThreads={[{ id: 6, title: 'Snoozed', format: 'Comic' }]}
      snoozedExpanded
      skippedThreads={[]}
      skippedExpanded
      blockedExpanded
      staleExpanded={false}
      unsnoozeIsPending
      unskipIsPending
      shuffleIsPending
      {...actions}
    /></MemoryRouter>)
    expect(screen.queryByText('Saga')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Shuffle queue' })).not.toBeInTheDocument()
    expect(screen.queryByText(/hidden \(blocked/)).not.toBeInTheDocument()
  })

  it('pluralizes multiple blocked threads and triggers read-stale on space key', async () => {
    // L158 `blockedThreads.length !== 1 ? 's' : ''` plus the stale roll button's native Space activation
    const actions = callbacks()
    const stale = { ...thread, title: 'Stale Saga', days: 9 }
    // SAFETY: Synthetic stale thread cast widens Thread to the stale shape with days for the pluralization test.
    render(<StaleSectionHarness
      pool={[thread]}
      blockedThreads={[{ ...thread, id: 2, title: 'Blocked A' }, { ...thread, id: 3, title: 'Blocked B' }]}
      blockingDependencyMap={{ 2: [{ thread_id: 9, thread_title: 'Saga', issue_number: '1', label: 'Read Saga first' }] }}
      isRatingView={false}
      selectedThreadId={null}
      staleThread={cast<Parameters<typeof ThreadPool>[0]['staleThread']>(stale)}
      staleThreadCount={1}
      snoozedThreads={[]}
      snoozedExpanded={false}
      skippedThreads={[]}
      skippedExpanded={false}
      blockedExpanded
      unsnoozeIsPending={false}
      unskipIsPending={false}
      shuffleIsPending={false}
      {...actions}
    />)
    expect(screen.getByText(/2 series waiting for earlier issues/)).toBeInTheDocument()
    // SAFETY: the stale section is collapsed by default; the roll affordance is only
    // reachable after expanding it, so toggle it open first.
    await userEvent.setup().click(screen.getByRole('button', { name: /series you haven't opened recently/i }))
    const staleRollButton = screen.getByRole('button', { name: /roll this series now/i })
    // SAFETY: the roll control is a native <button>, so Space activates it on keyup the way a
    // browser would; drive the real activation path instead of a bare keydown event.
    staleRollButton.focus()
    await userEvent.keyboard(' ')
    expect(actions.onReadStale).toHaveBeenCalledWith(thread.id)
  })
})

describe('RatingView', () => {
  function makeData(overrides: Partial<RatingViewData> = {}): RatingViewData {
    return {
      activeRatingThread: { id: 1, title: 'Saga', format: 'Comic', issues_remaining: 5, total_issues: 10, issue_number: '3', next_issue_number: '4', reading_progress: 'in_progress', queue_position: 0, issue_id: 100, next_issue_id: 101 },
      currentDie: 6, rolledResult: 3, rating: 3.0, predictedDie: 8, errorMessage: '', rateIsPending: false, snoozeIsPending: false, dismissIsPending: false, skipIsPending: false, manualDie: null, onUpdateRating: vi.fn(), onSubmitRating: vi.fn(), onSnooze: vi.fn(), onCancel: vi.fn(), onRefreshThread: vi.fn(), readerContext: null, isReaderContextLoading: false, readerContextError: null, ratingViewTopRef: null, issuesRemaining: 5, readingContextRequested: false, readingBoundariesRequested: false, readingOrders: [], connectedThreads: [], onShowContext: vi.fn(), onShowBoundaries: vi.fn(), readingOrdersIsLoading: false, readingOrdersError: null, connectedThreadsIsLoading: false, connectedThreadsError: null, ...overrides,
    }
  }

  it('renders rating states and invokes controls', async () => {
    const onUpdateRating = vi.fn(); const onSubmitRating = vi.fn(); const onSnooze = vi.fn(); const onCancel = vi.fn(); const onRefreshThread = vi.fn()
    const user = userEvent.setup()
    render(<MemoryRouter><RatingView data={makeData({ rating: 5, onUpdateRating, onSubmitRating, onSnooze, onCancel, onRefreshThread })} /></MemoryRouter>)
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
    await user.click(screen.getByRole('button', { name: /snooze/i }))
    expect(onSubmitRating).toHaveBeenCalled()
    expect(onSnooze).toHaveBeenCalled()
  })

  it('renders empty, low-rating, progress, reading-order, and correction states', async () => {
    const callbacks = { onUpdateRating: vi.fn(), onSubmitRating: vi.fn(), onSnooze: vi.fn(), onCancel: vi.fn(), onRefreshThread: vi.fn() }
    render(<MemoryRouter><RatingView data={makeData({ activeRatingThread: { id: 1, title: 'Saga', format: 'Comic', issues_remaining: 1, total_issues: 10, issue_number: '2', next_issue_number: null, reading_progress: 'completed', queue_position: 0, issue_id: 100, next_issue_id: null }, rating: 1, errorMessage: 'Oops', snoozeIsPending: true, onUpdateRating: callbacks.onUpdateRating, onSubmitRating: callbacks.onSubmitRating, onSnooze: callbacks.onSnooze, onCancel: callbacks.onCancel, onRefreshThread: callbacks.onRefreshThread })} /></MemoryRouter>)
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
    await userEvent.setup().click(screen.getByRole('button', { name: 'Snoozing…' }))
    await userEvent.setup().click(screen.getByRole('button', { name: 'Cancel roll' }))
  })

  it('renders safe fallbacks for missing thread metadata', async () => {
    render(<MemoryRouter><RatingView data={makeData({ activeRatingThread: { id: 1, title: 'Saga', format: 'Comic', issues_remaining: 1, total_issues: 10, issue_number: '2', next_issue_number: null, reading_progress: null, queue_position: 0, issue_id: 100, next_issue_id: null }, onUpdateRating: vi.fn(), onSubmitRating: vi.fn(), onSnooze: vi.fn(), onCancel: vi.fn(), onRefreshThread: vi.fn() })} /></MemoryRouter>)
    expect(screen.getByText('Saga')).toBeInTheDocument()
    expect(screen.queryByText('Why this?')).not.toBeInTheDocument()
    expect(screen.getByTestId('reading-context-button')).toBeInTheDocument()
    expect(screen.getByTestId('reading-boundaries-button')).toBeInTheDocument()
    expect(screen.getByTestId('rating-region-reading-optional')).toBeInTheDocument()
  })

  it('renders alternate rating, progress, and order boundaries', async () => {
    const callbacks = { onUpdateRating: vi.fn(), onSubmitRating: vi.fn(), onSnooze: vi.fn(), onCancel: vi.fn(), onRefreshThread: vi.fn() }
    render(<MemoryRouter><RatingView data={makeData({ activeRatingThread: { id: 1, title: 'Saga', format: 'Comic', issues_remaining: 2, total_issues: 0, issue_number: null, next_issue_number: null, reading_progress: null, queue_position: 0, issue_id: 100, next_issue_id: null }, rating: 5, predictedDie: 6, rolledResult: 2, onUpdateRating: callbacks.onUpdateRating, onSubmitRating: callbacks.onSubmitRating, onSnooze: callbacks.onSnooze, onCancel: callbacks.onCancel, onRefreshThread: callbacks.onRefreshThread })} /></MemoryRouter>)
    expect(screen.getByText('Saga')).toBeInTheDocument()
    expect(screen.queryByText('Die stays the same')).not.toBeInTheDocument()
    expect(screen.getByTestId('reading-context-button')).toBeInTheDocument()
    expect(screen.getByTestId('rating-region-reading-optional')).toBeInTheDocument()
    await userEvent.setup().click(screen.getByRole('button', { name: 'Mark read & save' }))
    expect(callbacks.onSubmitRating).toHaveBeenCalledWith(false)
  })

  it('asserts Why this? stays absent while collapsed Reading Context and Reading Boundaries cards are present', async () => {
    render(<MemoryRouter><RatingView data={makeData({ activeRatingThread: { id: 1, title: 'Saga', format: 'Comic', issues_remaining: 1, total_issues: 10, issue_number: '2', next_issue_number: null, reading_progress: null, queue_position: 0, issue_id: 100, next_issue_id: null }, onUpdateRating: vi.fn(), onSubmitRating: vi.fn(), onSnooze: vi.fn(), onCancel: vi.fn(), onRefreshThread: vi.fn() })} /></MemoryRouter>)
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
