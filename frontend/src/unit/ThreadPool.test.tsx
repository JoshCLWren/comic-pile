import React from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ThreadPool } from '../pages/RollPage/components/ThreadPool'
import type { Thread, BlockedThreadDetail } from '../types'

const mockNavigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  }
})

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
      // Check that navigate was called
      expect(mockNavigate).toHaveBeenCalledWith('/queue?highlight=1&scroll=true')
    }
  })

  it('limits initial display to 10 blocked threads and shows all on button click', async () => {
    const user = userEvent.setup()
    const manyThreads: BlockedThreadDetail[] = Array.from({ length: 12 }, (_, i) => ({
      id: i + 1,
      title: `Thread ${i + 1}`,
      format: 'Comic',
      queue_position: i + 1,
      primary_blocking_reason: `blocked by Dep ${i + 1}`
    }))
    function ManyTestWrapper() {
      const [blockedExpanded, setBlockedExpanded] = React.useState(false)
      return (
        <ThreadPool
          pool={[]}
          blockedThreadsWithReasons={manyThreads}
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
    render(<ManyTestWrapper />)
    // Open blocked section
    const toggleBtn = screen.getByRole('button', { name: /hidden/i })
    await user.click(toggleBtn)
    // Verify first 10 are present
    for (let i = 1; i <= 10; i++) {
      expect(screen.getByText(`Thread ${i}`)).toBeInTheDocument()
    }
    // Verify 11 and 12 not present
    expect(screen.queryByText('Thread 11')).not.toBeInTheDocument()
    expect(screen.queryByText('Thread 12')).not.toBeInTheDocument()
    // Click show all button
    const showAllBtn = screen.getByText(/show 2 more/i)
    await user.click(showAllBtn)
    // Now all 12 should be present
    for (let i = 1; i <= 12; i++) {
      expect(screen.getByText(`Thread ${i}`)).toBeInTheDocument()
    }
  })
})
