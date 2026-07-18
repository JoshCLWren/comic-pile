import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { ThreadPool } from '../pages/RollPage/components/ThreadPool'
import { RatingView } from '../pages/RollPage/components/RatingView'
import type { Thread } from '../types'

vi.mock('../components/LazyDice3D', () => ({ default: () => <div data-testid="dice" /> }))
vi.mock('../components/Tooltip', () => ({ default: ({ children }: { children: React.ReactNode }) => <>{children}</> }))
vi.mock('../components/IssueCorrectionDialog', () => ({ default: ({ isOpen, onClose, onSuccess }: { isOpen: boolean; onClose: () => void; onSuccess: () => void }) => isOpen ? <><button onClick={onClose}>Close correction</button><button onClick={onSuccess}>Correct successfully</button></> : null }))

const thread = { id: 1, title: 'Saga', format: 'Comic', issues_remaining: 5, total_issues: 10, next_unread_issue_number: '3' } as Thread
const callbacks = () => ({
  onThreadClick: vi.fn(), onUnsnooze: vi.fn(), onReadStale: vi.fn(), onToggleSnoozed: vi.fn(),
  onToggleBlocked: vi.fn(), onShuffle: vi.fn(),
})

describe('ThreadPool', () => {
  it('renders empty, blocked, pool, stale, and snoozed states', async () => {
    const empty = callbacks()
    const { rerender } = render(<MemoryRouter><ThreadPool pool={[]} blockedThreads={[]} blockingReasonMap={{}} isRatingView={false} isRolling={false} rolledResult={null} selectedThreadId={null} staleThread={null} staleThreadCount={0} snoozedThreads={[]} snoozedExpanded={false} blockedExpanded={false} unsnoozeIsPending={false} shuffleIsPending={false} {...empty} /></MemoryRouter>)
    expect(screen.getByText('Nothing to roll yet')).toBeInTheDocument()
    await userEvent.setup().click(screen.getByRole('button', { name: /add a thread/i }))
    expect(empty.onShuffle).not.toHaveBeenCalled()

    const actions = callbacks()
    rerender(<MemoryRouter><ThreadPool pool={[]} blockedThreads={[{ ...thread, id: 2, title: 'Blocked' }]} blockingReasonMap={{ 2: ['Read Saga first'] }} isRatingView={false} isRolling={false} rolledResult={null} selectedThreadId={null} staleThread={{ ...thread, days: 4 } as never} staleThreadCount={2} snoozedThreads={[{ id: 3, title: 'Snoozed', format: 'Comic' }]} snoozedExpanded={false} blockedExpanded={false} unsnoozeIsPending={false} shuffleIsPending={false} {...actions} /></MemoryRouter>)
    expect(screen.getByText(/All threads are blocked/)).toBeInTheDocument()
    await userEvent.setup().click(screen.getByRole('button', { name: /go to queue/i }))
    expect(actions.onToggleBlocked).not.toHaveBeenCalled()

    rerender(<MemoryRouter><ThreadPool pool={[thread]} blockedThreads={[]} blockingReasonMap={{}} isRatingView={false} isRolling={false} rolledResult={null} selectedThreadId={1} staleThread={{ ...thread, days: 2 } as never} staleThreadCount={1} snoozedThreads={[{ id: 3, title: 'Snoozed', format: 'Comic' }]} snoozedExpanded={false} blockedExpanded={false} unsnoozeIsPending={false} shuffleIsPending={false} {...actions} /></MemoryRouter>)
    await userEvent.setup().click(screen.getByRole('button', { name: /snoozed/i }))
    await userEvent.setup().click(screen.getAllByText('Saga')[0]!)
    expect(actions.onThreadClick).toHaveBeenCalledWith(thread)
    fireEvent.keyDown(screen.getAllByText('Saga')[0]!.closest('[role="button"]')!, { key: 'Enter' })
    expect(actions.onThreadClick).toHaveBeenCalledTimes(2)
  })

  it('covers expanded blocked, stale, snoozed, selected, rolling, and disabled controls', async () => {
    const actions = callbacks()
    const stale = { ...thread, title: 'Stale Saga', days: 9 } as never
    render(<MemoryRouter><ThreadPool pool={[]} blockedThreads={[{ ...thread, id: 2, title: 'Blocked' }]} blockingReasonMap={{ 2: ['Prerequisite'] }} isRatingView={false} isRolling={false} rolledResult={null} selectedThreadId={null} staleThread={stale} staleThreadCount={2} snoozedThreads={[{ id: 3, title: 'Snoozed', format: 'Comic' }]} snoozedExpanded={true} blockedExpanded={true} unsnoozeIsPending={false} shuffleIsPending={false} {...actions} /></MemoryRouter>)
    await userEvent.setup().click(screen.getByRole('button', { name: /hidden \(blocked/i }))
    expect(screen.getByText('Prerequisite')).toBeInTheDocument()
    fireEvent.keyDown(screen.getByRole('button', { name: /hidden \(blocked/i }), { key: 'ArrowDown' })
    await userEvent.setup().click(screen.getByRole('button', { name: /Snoozed \(1\)/i }))
    await userEvent.setup().click(screen.getByRole('button', { name: 'Unsnooze this comic' }))
    expect(actions.onUnsnooze).toHaveBeenCalledWith(3)
    const staleCard = screen.getByText(/Stale Saga/).closest('[role="button"]') as HTMLElement
    fireEvent.keyDown(staleCard, { key: 'Enter' })
    expect(actions.onReadStale).toHaveBeenCalled()
  })
})

describe('RatingView', () => {
  it('renders rating states and invokes controls', async () => {
    const onUpdateRating = vi.fn(); const onSubmitRating = vi.fn(); const onSnooze = vi.fn(); const onCancel = vi.fn(); const onRefreshThread = vi.fn()
    const user = userEvent.setup()
    render(<RatingView activeRatingThread={{ ...thread, id: 1, issue_number: '2', next_issue_number: '3', reading_progress: 'in_progress' } as never} currentDie={20} rolledResult={19} rating={5} predictedDie={6} hasValidRolledResult poolSize={6} errorMessage="Problem" rateIsPending={false} snoozeIsPending={false} dismissIsPending={false} readingOrders={[]} connectedThreads={[{ thread_id: 2, title: 'Other', connection_type: 'blocks', dependency_id: 1 }]} onUpdateRating={onUpdateRating} onSubmitRating={onSubmitRating} onSnooze={onSnooze} onCancel={onCancel} onRefreshThread={onRefreshThread} />)
    expect(screen.getByText(/You rolled a 19/)).toBeInTheDocument()
    expect(screen.getByText(/pool size: 6/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /correct issue number/i }))
    await user.click(screen.getByRole('button', { name: /close correction/i }))
    const rating = screen.getByRole('slider')
    fireEvent.change(rating, { target: { value: '3' } })
    expect(onUpdateRating).toHaveBeenCalledWith('3')
    await user.click(screen.getByRole('button', { name: /save & continue/i }))
    await user.click(screen.getByRole('button', { name: /snooze/i }))
    expect(onSubmitRating).toHaveBeenCalled()
    expect(onSnooze).toHaveBeenCalled()
  })

  it('renders empty, low-rating, progress, reading-order, and correction states', async () => {
    const callbacks = { onUpdateRating: vi.fn(), onSubmitRating: vi.fn(), onSnooze: vi.fn(), onCancel: vi.fn(), onRefreshThread: vi.fn() }
    const user = userEvent.setup()
    render(<RatingView activeRatingThread={{ ...thread, issue_number: '2', next_issue_number: null, reading_progress: 'completed', issues_remaining: 1 } as never} currentDie={4} rolledResult={null} rating={1} predictedDie={6} hasValidRolledResult={false} poolSize={2} errorMessage="Oops" rateIsPending snoozeIsPending dismissIsPending readingOrders={[{ id: 1, name: 'Order', description: '', completed_items: 0, total_items: 0 } as never]} connectedThreads={[{ thread_id: 2, title: 'Other', connection_type: 'blocks', dependency_id: 1 }]} {...callbacks} />)
    expect(screen.getByText(/This is the last issue/)).toBeInTheDocument()
    expect(screen.getByText('Oops')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /correct issue number/i }))
    await user.click(screen.getByRole('button', { name: 'Correct successfully' }))
    expect(callbacks.onRefreshThread).toHaveBeenCalled()
    fireEvent.change(screen.getByRole('slider'), { target: { value: '2' } })
    await user.click(screen.getByRole('button', { name: 'Snoozing...' }))
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
  })
})
