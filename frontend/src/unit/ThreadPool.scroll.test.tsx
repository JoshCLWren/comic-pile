import { render } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ThreadPool } from '../pages/RollPage/components/ThreadPool'

const baseProps = {
  pool: [],
  blockedThreads: [],
  blockingReasonMap: {},
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

afterEach(() => {
  vi.restoreAllMocks()
})

describe('ThreadPool roll return position', () => {
  it('scrolls to the top when leaving the rating view', () => {
    const scrollTo = vi.spyOn(window, 'scrollTo').mockImplementation(() => undefined)
    const { rerender } = render(
      <MemoryRouter>
        <ThreadPool {...baseProps} isRatingView />
      </MemoryRouter>,
    )

    expect(scrollTo).not.toHaveBeenCalled()

    rerender(
      <MemoryRouter>
        <ThreadPool {...baseProps} isRatingView={false} />
      </MemoryRouter>,
    )

    expect(scrollTo).toHaveBeenCalledTimes(1)
    expect(scrollTo).toHaveBeenCalledWith({ top: 0, left: 0, behavior: 'auto' })
  })

  it('does not reset scroll during ordinary roll-pool rerenders', () => {
    const scrollTo = vi.spyOn(window, 'scrollTo').mockImplementation(() => undefined)
    const { rerender } = render(
      <MemoryRouter>
        <ThreadPool {...baseProps} isRatingView={false} />
      </MemoryRouter>,
    )

    rerender(
      <MemoryRouter>
        <ThreadPool {...baseProps} isRatingView={false} snoozedExpanded />
      </MemoryRouter>,
    )

    expect(scrollTo).not.toHaveBeenCalled()
  })
})
