import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { ThreadPool } from '../ThreadPool'
import type { Thread, BlockedThreadDetail } from '../../../types'

describe('ThreadPool blocked threads UI', () => {
  const blockedDetails: BlockedThreadDetail[] = [
    {
      id: 2,
      title: 'Blocked One',
      format: 'Comic',
      queue_position: 10,
      primary_blocking_reason: 'blocked by Thread X #5',
    },
    {
      id: 3,
      title: 'Blocked Two',
      format: 'Graphic Novel',
      queue_position: 11,
      primary_blocking_reason: 'blocked by Thread Y #1',
    },
  ]

  test('shows collapsed button when not expanded', () => {
    render(
      <MemoryRouter>
        <ThreadPool
          pool={[]}
          blockedThreadsWithReasons={blockedDetails}
          isRatingView={false}
          isRolling={false}
          rolledResult={null}
          selectedThreadId={null}
          staleThread={null}
          staleThreadCount={0}
          snoozedThreads={[]}
          snoozedExpanded={false}
          blockedExpanded={false}
          onThreadClick={jest.fn()}
          onUnsnooze={jest.fn()}
          onReadStale={jest.fn()}
          onToggleSnoozed={jest.fn()}
          onToggleBlocked={jest.fn()}
          unsnoozeIsPending={false}
        />
      </MemoryRouter>,
    )

    const button = screen.getByRole('button', { name: /2 threads hidden/i })
    expect(button).toBeInTheDocument()
    expect(button).toHaveTextContent('▶')
  })

  test('expands to show blocked threads with reasons', () => {
    render(
      <MemoryRouter>
        <ThreadPool
          pool={[]}
          blockedThreadsWithReasons={blockedDetails}
          isRatingView={false}
          isRolling={false}
          rolledResult={null}
          selectedThreadId={null}
          staleThread={null}
          staleThreadCount={0}
          snoozedThreads={[]}
          snoozedExpanded={false}
          blockedExpanded={true}
          onThreadClick={jest.fn()}
          onUnsnooze={jest.fn()}
          onReadStale={jest.fn()}
          onToggleSnoozed={jest.fn()}
          onToggleBlocked={jest.fn()}
          unsnoozeIsPending={false}
        />
      </MemoryRouter>,
    )

    blockedDetails.forEach((t) => {
      expect(screen.getByText(t.title)).toBeInTheDocument()
      expect(screen.getByText(t.primary_blocking_reason)).toBeInTheDocument()
    })
  })
})
