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
      name: /Die face 1: Amazing Adventures, issue 12, routes Secret War/i,
    })).toBeVisible()
    expect(screen.getByRole('button', { name: 'Shuffle queue' })).toHaveAccessibleDescription(
      /complete active queue/i,
    )

    const dieFace = screen.getByRole('button', { name: /Die face 1: Amazing Adventures/i })
    const titleText = dieFace.querySelector('p:nth-of-type(1)')
    const issueText = dieFace.querySelector('p:nth-of-type(2)')
    expect(titleText?.textContent).toBe('Amazing Adventures')
    expect(issueText?.textContent).toBe('Issue 12')
    expect(titleText).toHaveClass('font-bold', 'text-sm', 'text-stone-200')
    expect(issueText).toHaveClass('text-xs', 'text-stone-400')
    expect(issueText).not.toHaveClass('font-bold', 'text-sm')
    expect(
      titleText && issueText
        ? titleText.compareDocumentPosition(issueText) & Node.DOCUMENT_POSITION_FOLLOWING
        : 0,
    ).toBeTruthy()
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
