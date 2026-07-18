import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import RollPage from '../pages/RollPage'

const spies = vi.hoisted(() => ({
  navigate: vi.fn(), refetch: vi.fn().mockResolvedValue({}), mutate: vi.fn().mockResolvedValue({}),
  setPending: vi.fn().mockResolvedValue({ thread_id: 1, title: 'Saga', format: 'Comic', issues_remaining: 2, queue_position: 1, total_issues: 10, result: 3 }),
}))
const sessionData = { current_die: 6, snoozed_threads: [] }
const threadData = [{ id: 1, title: 'Saga', format: 'Comic', status: 'active' }]
const staleData: never[] = []

vi.mock('react-router-dom', () => ({ useNavigate: () => spies.navigate }))
vi.mock('../config/featureFlags', () => ({ collectionsEnabled: false, isReviewsFeatureEnabled: () => false }))
vi.mock('../contexts/CollectionContext', () => ({ useCollections: () => ({ activeCollectionId: null }) }))
vi.mock('../contexts/useBugReportRestore', () => ({ useBugReportRestore: () => ({ setRestoreAction: vi.fn(), clearRestoreAction: vi.fn() }) }))
vi.mock('../hooks/useSession', () => ({ useSession: () => ({ data: sessionData, refetch: spies.refetch }) }))
vi.mock('../hooks/useThread', () => ({ useThreads: () => ({ data: threadData, refetch: spies.refetch }), useStaleThreads: () => ({ data: staleData, refetch: spies.refetch }) }))
vi.mock('../hooks/useRoll', () => ({
  useSetDie: () => ({ mutate: spies.mutate, isPending: false }), useClearManualDie: () => ({ mutate: spies.mutate, isPending: false }),
  useRoll: () => ({ mutate: spies.mutate, isPending: false }), useDismissPending: () => ({ mutate: spies.mutate, isPending: false }),
  useOverrideRoll: () => ({ mutate: spies.mutate, isPending: false }),
}))
vi.mock('../hooks/useSnooze', () => ({ useSnooze: () => ({ mutate: spies.mutate, isPending: false }), useUnsnooze: () => ({ mutate: spies.mutate, isPending: false }) }))
vi.mock('../hooks/useQueue', () => ({ useMoveToFront: () => ({ mutate: spies.mutate, isPending: false }), useMoveToBack: () => ({ mutate: spies.mutate, isPending: false }), useShuffleQueue: () => ({ mutate: spies.mutate, isPending: false }) }))
vi.mock('../hooks', () => ({ useRate: () => ({ mutate: spies.mutate, isPending: false }) }))
vi.mock('../services/api', () => ({ threadsApi: { setPending: spies.setPending }, dependenciesApi: { getConnectedThreads: vi.fn().mockResolvedValue({ connected_threads: [] }) } }))
vi.mock('../services/api-reading-orders', () => ({ readingOrdersApi: { getForThread: vi.fn().mockResolvedValue({ reading_orders: [] }) } }))
vi.mock('../services/api-reviews', () => ({ reviewsApi: { createOrUpdateReview: spies.mutate } }))
vi.mock('../components/LazyDice3D', () => ({ default: () => <div data-testid="dice" /> }))
vi.mock('../components/Tooltip', () => ({ default: ({ children }: { children: React.ReactNode }) => <>{children}</> }))
vi.mock('../components/Modal', () => ({ default: ({ isOpen, title, children, onClose }: { isOpen: boolean; title: string; children: React.ReactNode; onClose: () => void }) => isOpen ? <section><h2>{title}</h2><button onClick={onClose}>close modal</button>{children}</section> : null }))
vi.mock('../components/CollectionDialog', () => ({ default: () => <div>collection dialog</div> }))
vi.mock('../components/MigrationDialog', () => ({ default: ({ onComplete, onSkip, onClose }: { onComplete: (thread: unknown) => void; onSkip: () => void; onClose: () => void }) => <div><button onClick={onSkip}>skip migration</button><button onClick={onClose}>close migration</button><button onClick={() => onComplete({ id: 1, title: 'Saga', format: 'Comic', issues_remaining: 2, queue_position: 1, total_issues: 10 })}>complete migration</button></div> }))
vi.mock('../components/SimpleMigrationDialog', () => ({ default: ({ onComplete, onClose }: { onComplete: (issue: string) => void; onClose: () => void }) => <div><button onClick={() => onComplete('1')}>complete simple</button><button onClick={onClose}>close simple</button></div> }))
vi.mock('../components/ReviewForm', () => ({ default: ({ onSubmit, onClose }: { onSubmit: (data: { review_text: string }) => void; onClose: () => void }) => <div><button onClick={() => onSubmit({ review_text: '' })}>submit review</button><button onClick={onClose}>close review</button></div> }))
vi.mock('../pages/RollPage/components/ThreadPool', () => ({ ThreadPool: (props: Record<string, unknown>) => <div><button onClick={() => (props.onThreadClick as (thread: unknown) => void)({ id: 1, title: 'Saga', format: 'Comic' })}>thread</button><button onClick={props.onShuffle as () => void}>shuffle pool</button><button onClick={props.onReadStale as () => void}>read stale</button><button onClick={props.onUnsnooze as () => void}>unsnooze</button><button onClick={props.onToggleSnoozed as () => void}>toggle snoozed</button><button onClick={props.onToggleBlocked as () => void}>toggle blocked</button></div> }))
vi.mock('../pages/RollPage/components/RatingView', () => ({ RatingView: (props: Record<string, unknown>) => <div><button onClick={() => (props.onUpdateRating as (value: string) => void)('5')}>update rating</button><button onClick={props.onSubmitRating as () => void}>save rating</button><button onClick={props.onSnooze as () => void}>snooze rating</button><button onClick={props.onCancel as () => void}>cancel rating</button><button onClick={props.onRefreshThread as () => void}>refresh rating</button></div> }))

describe('RollPage parent handlers', () => {
  it('executes pool actions, roll recovery, and modal callbacks', async () => {
    render(<RollPage />)
    await fireEvent.click(screen.getByRole('button', { name: 'thread' }))
    expect(screen.getByRole('heading', { name: 'Saga' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Read Now/ }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'save rating' })).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'update rating' }))
    fireEvent.click(screen.getByRole('button', { name: 'refresh rating' }))
    fireEvent.click(screen.getByRole('button', { name: 'save rating' }))
    await waitFor(() => expect(screen.queryByRole('button', { name: 'save rating' })).not.toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /^Override$/ }))
    fireEvent.click(screen.getByRole('button', { name: 'close modal' }))
    fireEvent.click(screen.getByRole('button', { name: 'shuffle pool' }))
    fireEvent.click(screen.getByRole('button', { name: 'toggle snoozed' }))
    fireEvent.click(screen.getByRole('button', { name: 'toggle blocked' }))
    expect(spies.mutate).toHaveBeenCalled()
  })

  it('executes the remaining selected-thread actions and die controls', async () => {
    render(<RollPage />)
    const user = userEvent.setup()
    const openActions = async () => user.click(screen.getByRole('button', { name: 'thread' }))
    await openActions()
    await user.click(screen.getByRole('button', { name: /move to front/i }))
    await openActions()
    await user.click(screen.getByRole('button', { name: /move to back/i }))
    await openActions()
    const snoozeAction = screen.getAllByRole('button', { name: /snooze/i })
      .find((button) => button.textContent?.includes('Snooze') && !button.textContent?.includes('toggle'))
    if (!snoozeAction) throw new Error('Snooze action not found')
    await user.click(snoozeAction)
    await openActions()
    await user.click(screen.getByRole('button', { name: /edit thread/i }))
    expect(spies.navigate).toHaveBeenCalledWith('/queue', { state: { editThreadId: 1 } })

    await user.click(screen.getAllByRole('button', { name: 'd6' })[0]!)
    await user.click(screen.getAllByRole('button', { name: 'd4' })[0]!)
    await user.click(screen.getByRole('button', { name: 'Auto' }))
    expect(spies.mutate).toHaveBeenCalled()
  })
})
