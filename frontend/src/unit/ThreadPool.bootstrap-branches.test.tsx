import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { ThreadPool } from '../pages/RollPage/components/ThreadPool'

const navigate = vi.fn()

vi.mock('react-router-dom', async (importOriginal) => ({
  ...await importOriginal<typeof import('react-router-dom')>(),
  useNavigate: () => navigate,
}))

describe('ThreadPool bootstrap edge branches', () => {
  it('retains keyboard access with a zero selected id while ignoring retired blocked reports', () => {
    const onThreadClick = vi.fn()

    render(
      <MemoryRouter><ThreadPool
        pool={[{ id: 1, title: 'Saga', format: 'Comic' }]}
        blockedThreads={[{ id: 2, title: 'Monstress', format: 'Comic' }]}
        blockingDependencyMap={{}}
        isRatingView={false}
        selectedThreadId={0}
        staleThread={null}
        staleThreadCount={0}
        snoozedThreads={[]}
        snoozedExpanded={false}
        skippedThreads={[]}
        skippedExpanded={false}
        blockedExpanded
        staleExpanded={false}
        onThreadClick={onThreadClick}
        onUnsnooze={vi.fn()}
        onUnskip={vi.fn()}
        onReadStale={vi.fn()}
        onToggleSnoozed={vi.fn()}
        onToggleSkipped={vi.fn()}
        onToggleStale={vi.fn()}
        onToggleBlocked={vi.fn()}
        onShuffle={vi.fn()}
        unsnoozeIsPending={false}
        unskipIsPending={false}
        shuffleIsPending={false}
      /></MemoryRouter>,
    )

    const thread = screen.getByRole('button', { name: /Die face 1: Saga/i })
    expect(thread).not.toHaveClass('pool-thread-selected')
    fireEvent.keyDown(thread, { key: 'Enter' })
    expect(onThreadClick).toHaveBeenCalledWith({ id: 1, title: 'Saga', format: 'Comic' })

    expect(screen.queryByRole('link', { name: 'Monstress' })).not.toBeInTheDocument()
    expect(screen.queryByText('Reading requirements are unavailable. Open the series to retry.')).not.toBeInTheDocument()
    expect(screen.queryByText('Read the prerequisite first')).not.toBeInTheDocument()
  })
})
