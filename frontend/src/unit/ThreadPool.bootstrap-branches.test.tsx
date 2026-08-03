import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ThreadPool } from '../pages/RollPage/components/ThreadPool'

const navigate = vi.fn()

vi.mock('react-router-dom', () => ({
  useNavigate: () => navigate,
}))

describe('ThreadPool bootstrap edge branches', () => {
  it('handles a zero selected id and a blocked thread without a reason', () => {
    const onThreadClick = vi.fn()

    render(
      <ThreadPool
        pool={[{ id: 1, title: 'Saga', format: 'Comic' }]}
        blockedThreads={[{ id: 2, title: 'Monstress', format: 'Comic' }]}
        blockingReasonMap={{}}
        isRatingView={false}
        isRolling={false}
        rolledResult={null}
        selectedThreadId={0}
        staleThread={null}
        staleThreadCount={0}
        snoozedThreads={[]}
        snoozedExpanded={false}
        blockedExpanded
        onThreadClick={onThreadClick}
        onUnsnooze={vi.fn()}
        onReadStale={vi.fn()}
        onToggleSnoozed={vi.fn()}
        onToggleBlocked={vi.fn()}
        onShuffle={vi.fn()}
        unsnoozeIsPending={false}
        shuffleIsPending={false}
      />,
    )

    const thread = screen.getByRole('button', { name: /Saga Comic/i })
    expect(thread).not.toHaveClass('pool-thread-selected')
    fireEvent.keyDown(thread, { key: 'Enter' })
    expect(onThreadClick).toHaveBeenCalledWith({ id: 1, title: 'Saga', format: 'Comic' })

    expect(screen.getByText('Monstress')).toBeInTheDocument()
    expect(screen.queryByText('Read the prerequisite first')).not.toBeInTheDocument()
  })
})
