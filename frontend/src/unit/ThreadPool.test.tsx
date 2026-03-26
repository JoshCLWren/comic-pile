import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BrowserRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import type { Thread } from '../types'
import { ThreadPool } from '../pages/RollPage/components/ThreadPool'

const baseThread: Thread = {
  id: 1,
  title: 'Saga',
  format: 'Comic',
  issues_remaining: 12,
  queue_position: 1,
  status: 'active',
  is_blocked: false,
  blocking_reasons: [],
  total_issues: null,
  next_unread_issue_id: null,
  next_unread_issue_number: null,
  reading_progress: null,
  collection_id: null,
  notes: null,
  created_at: '2024-01-01T00:00:00Z',
}

const renderThreadPool = (overrideProps: Partial<React.ComponentProps<typeof ThreadPool>> = {}) => {
  const defaultProps: React.ComponentProps<typeof ThreadPool> = {
    pool: [baseThread],
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
    unsnoozeIsPending: false,
    ...overrideProps,
  }

  return render(
    <BrowserRouter>
      <ThreadPool {...defaultProps} />
    </BrowserRouter>
  )
}

describe('ThreadPool blocked section', () => {
  it('shows collapsed summary with next-unlock teaser', () => {
    renderThreadPool({
      blockedThreads: [
        {
          ...baseThread,
          id: 2,
          title: 'Monstress',
          queue_position: 7,
          is_blocked: true,
          blocking_reasons: ['Read Ultimate Black Panther #1'],
        },
      ],
      blockingReasonMap: { 2: ['Read Ultimate Black Panther #1'] },
    })

    expect(screen.getByText(/Blocked \(1\)/i)).toBeInTheDocument()
    expect(screen.getByText(/Next unlock: Read Ultimate Black Panther #1/i)).toBeInTheDocument()
    expect(screen.queryByText('Monstress')).not.toBeInTheDocument()
  })

  it('reveals blocked threads when expanded', async () => {
    const user = userEvent.setup()
    const onToggleBlocked = vi.fn()
    renderThreadPool({
      blockedExpanded: true,
      onToggleBlocked,
      blockedThreads: [
        {
          ...baseThread,
          id: 3,
          title: 'Blocked Thread',
          queue_position: 4,
          is_blocked: true,
          blocking_reasons: ['Finish Stormwatch Vol. 1'],
        },
      ],
      blockingReasonMap: { 3: ['Finish Stormwatch Vol. 1'] },
    })

    expect(screen.getByText('Blocked Thread')).toBeInTheDocument()
    expect(screen.getByText('#4')).toBeInTheDocument()
    expect(screen.getByText(/Finish Stormwatch Vol\. 1/)).toBeInTheDocument()

    const summaryButton = screen.getByTestId('blocked-summary-toggle')
    await user.click(summaryButton)
    expect(onToggleBlocked).toHaveBeenCalled()
  })
})
