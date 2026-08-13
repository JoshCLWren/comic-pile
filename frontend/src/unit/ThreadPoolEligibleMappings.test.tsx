import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { ThreadPool } from '../pages/RollPage/components/ThreadPool'

const baseProps = {
  blockedThreads: [],
  blockingReasonMap: {},
  isRatingView: false,
  isRolling: false,
  rolledResult: null,
  selectedThreadId: null,
  staleThread: null,
  staleThreadCount: 0,
  snoozedThreads: [],
  snoozedExpanded: false,
  blockedExpanded: false,
  onThreadClick: vi.fn(),
  onUnsnooze: vi.fn(),
  onReadStale: vi.fn(),
  onToggleSnoozed: vi.fn(),
  onToggleBlocked: vi.fn(),
  onShuffle: vi.fn(),
  unsnoozeIsPending: false,
  shuffleIsPending: false,
}

describe('ThreadPool eligible mappings', () => {
  it('labels each die face with the authoritative issue identity', () => {
    render(
      <MemoryRouter>
        <ThreadPool
          {...baseProps}
          pool={[{
            id: 7,
            title: 'Amazing Adventures',
            format: 'ongoing',
            issue_id: 42,
            issue_number: '12',
            route_labels: ['Secret War'],
          }]}
        />
      </MemoryRouter>,
    )

    expect(screen.getByText('Eligible now · 1')).toBeVisible()
    expect(screen.getByText('Issue 12')).toBeVisible()
    expect(screen.getByRole('button', {
      name: /Die face 1: issue 12, Amazing Adventures, routes Secret War/i,
    })).toBeVisible()
    expect(screen.getByRole('button', { name: 'Shuffle queue' })).toHaveAccessibleDescription(
      /complete active queue/i,
    )
  })

  it('omits eligible mappings while rating', () => {
    render(
      <MemoryRouter>
        <ThreadPool
          {...baseProps}
          isRatingView
          pool={[{ id: 7, title: 'Amazing Adventures', format: 'ongoing', issue_number: '12' }]}
        />
      </MemoryRouter>,
    )

    expect(screen.queryByLabelText(/Eligible now/i)).not.toBeInTheDocument()
    expect(screen.queryByText('Issue 12')).not.toBeInTheDocument()
  })
})
