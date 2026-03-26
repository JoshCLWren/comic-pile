import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useNavigate } from 'react-router-dom'
import { ThreadPool } from '../pages/RollPage/components/ThreadPool'
import type { Thread, BlockedThreadDetail } from '../types'

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return {
    ...actual,
    useNavigate: vi.fn(),
  }
})

const mockedNavigate = vi.mocked(useNavigate)

function TestWrapper() {
  const [blockedExpanded, setBlockedExpanded] = React.useState(false)
  const blockedThreads: BlockedThreadDetail[] = [
    { id: 1, title: 'Thread A', format: 'Comic', queue_position: 1, primary_blocking_reason: 'blocked by B #1' },
    { id: 2, title: 'Thread B', format: 'Comic', queue_position: 2, primary_blocking_reason: 'blocked by C #2' },
  ]
  const pool: Thread[] = []
  return (
    <ThreadPool
      pool={pool}
      blockedThreadsWithReasons={blockedThreads}
      isRatingView={false}
      isRolling={false}
      rolledResult={null}
      selectedThreadId={null}
      staleThread={null}
      staleThreadCount={0}
      snoozedThreads={[]}
      snoozedExpanded={false}
      blockedExpanded={blockedExpanded}
      onThreadClick={() => {}}
      onUnsnooze={() => {}}
      onReadStale={() => {}}
      onToggleSnoozed={() => {}}
      onToggleBlocked={() => setBlockedExpanded(!blockedExpanded)}
      unsnoozeIsPending={false}
    />
  )
}

describe('ThreadPool blocked section', () => {
  it('toggles visibility of blocked threads list', async () => {
    const user = userEvent.setup()
    render(<TestWrapper />)
    const toggleBtn = screen.getByRole('button', { name: /hidden/i })
    expect(toggleBtn).toBeInTheDocument()
    expect(screen.queryByText('Thread A')).not.toBeInTheDocument()
    await user.click(toggleBtn)
    expect(screen.getByText('Thread A')).toBeInTheDocument()
    expect(screen.getByText('Thread B')).toBeInTheDocument()
    const firstRow = screen.getByText('Thread A').closest('button')
    if (firstRow) {
      await user.click(firstRow)
      expect(mockedNavigate).toHaveBeenCalledWith('/queue?highlight=1')
    }
  })
})
