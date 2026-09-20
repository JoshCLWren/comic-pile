import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { RatingView } from '../pages/RollPage/components/RatingView'
import { RATING_THRESHOLD } from '../pages/RollPage/utils'
import type { RatingViewData } from '../pages/RollPage/useRatingView'
vi.mock('../contexts/useToast', () => ({ useToast: () => ({ toasts: [], showToast: vi.fn(), removeToast: vi.fn() }) }))

vi.mock('../components/LazyDice3D', () => ({ default: () => <div data-testid="dice" /> }))
vi.mock('../components/Tooltip', () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))
vi.mock('../components/IssueCorrectionDialog', () => ({ default: () => null }))
vi.mock('../components/ContinuityCorrectionDialog', () => ({ default: () => null }))
vi.mock('../pages/RollPage/components/ReadingOrderGroups', () => ({
  ReadingOrderGroups: () => null,
}))
vi.mock('../pages/RollPage/components/ComicVineIssueCard', () => ({
  ComicVineIssueCard: () => null,
}))
vi.mock('../pages/RollPage/components/ReadingRouteExplanation', () => ({
  ReadingRouteExplanation: () => null,
}))
vi.mock('../hooks/useReaderContext', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../hooks/useReaderContext')>()
  return {
    ...actual,
    useReaderContext: () => ({
      context: null,
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    }),
  }
})

function makeRatingViewData(overrides: Partial<RatingViewData> = {}): RatingViewData {
  const thread = overrides.activeRatingThread ?? {
    id: 1,
    title: 'Saga',
    format: 'Comic',
    issues_remaining: 5,
    total_issues: 10,
    issue_number: '3',
    next_issue_number: '4',
    reading_progress: 'in_progress',
    queue_position: 0,
    issue_id: 100,
    next_issue_id: 101,
  }
  return {
    activeRatingThread: thread,
    currentDie: 6,
    rolledResult: 3,
    rating: 3.0,
    predictedDie: 8,
    errorMessage: '',
    rateIsPending: false,
    snoozeIsPending: false,
    dismissIsPending: false,
    skipIsPending: false,
    onUpdateRating: vi.fn(),
    onSubmitRating: vi.fn(),
    onSnooze: vi.fn(),
    onSkip: undefined,
    onCancel: vi.fn(),
    onRefreshThread: vi.fn(),
    readerContext: null,
    isReaderContextLoading: false,
    readerContextError: null,
    ratingViewTopRef: null,
    issuesRemaining: thread.issues_remaining,
    ...overrides,
  }
}

function ratingView(overrides: Partial<RatingViewData> = {}) {
  return (
    <MemoryRouter>
      <RatingView data={makeRatingViewData(overrides)} />
    </MemoryRouter>
  )
}

describe('RatingView action panel (issue #1406)', () => {
  it('Cancel uses demoted tertiary styling that does not rival the primary save', () => {
    render(ratingView())
    const cancel = screen.getByRole('button', { name: /cancel roll/i })
    expect(cancel.className).toContain('border-[var(--theme-border)]')
    expect(cancel.className).toContain('bg-transparent')
    expect(cancel.className).toContain('text-[var(--theme-text-muted)]')
    expect(cancel.className).not.toContain('rose')
    expect(cancel.className).not.toContain('focus:ring-rose-500')
  })

  it('Snooze remains neutral styling', () => {
    render(ratingView())
    const snooze = screen.getByRole('button', { name: /snooze/i })
    expect(snooze.className).toContain('border-[var(--theme-border)]')
    expect(snooze.className).toContain('bg-[var(--theme-bg-panel)]')
    expect(snooze.className).toContain('text-stone-300')
  })

  it('Snooze and Cancel are equal width (both flex-1)', () => {
    render(ratingView())
    const snooze = screen.getByRole('button', { name: /snooze/i })
    const cancel = screen.getByRole('button', { name: /cancel roll/i })
    expect(snooze.className).toContain('flex-1')
    expect(cancel.className).toContain('flex-1')
  })

  it('primary save remains the dominant hierarchy over Cancel (issue #2347)', () => {
    render(ratingView())
    const save = screen.getByRole('button', { name: /mark read & save/i })
    const cancel = screen.getByRole('button', { name: /cancel roll/i })
    const primary = save.classList.contains('bg-[var(--theme-comic-accent)]/25')
    const cancelIsDemoted =
      cancel.classList.contains('bg-transparent') &&
      cancel.classList.contains('text-[var(--theme-text-muted)]')
    expect(primary).toBe(true)
    expect(cancelIsDemoted).toBe(true)
    expect(save.classList.contains('w-full')).toBe(true)
    expect(cancel.className).not.toContain('rose')
  })

  it('shows dN → dM die consequence', () => {
    render(ratingView({ currentDie: 6, predictedDie: 4 }))
    expect(screen.getByText('d6 → d4')).toBeInTheDocument()
    expect(screen.getByText('More focused next roll')).toBeInTheDocument()
  })

  it('shows step-up consequence for rating below threshold', () => {
    render(ratingView({ currentDie: 6, predictedDie: 8, rating: 3.0 }))
    expect(screen.getByText('d6 → d8')).toBeInTheDocument()
    expect(screen.getByText('More variety next roll')).toBeInTheDocument()
  })

  it('shows step-down consequence for rating at or above threshold', () => {
    render(ratingView({ currentDie: 6, predictedDie: 4, rating: RATING_THRESHOLD }))
    expect(screen.getByText('d6 → d4')).toBeInTheDocument()
    expect(screen.getByText('More focused next roll')).toBeInTheDocument()
  })

  it('shows boundary die same when rating is neutral', () => {
    render(ratingView({ currentDie: 6, predictedDie: 6, rating: 3.0 }))
    expect(screen.getByText('d6 → d6')).toBeInTheDocument()
    expect(screen.getByText('Die stays the same')).toBeInTheDocument()
  })

  it('primary action shows Mark read & save for multi-issue thread', () => {
    render(ratingView({ issuesRemaining: 5 }))
    expect(screen.getByRole('button', { name: /mark read & save/i })).toBeInTheDocument()
  })

  it('primary action shows Mark read & complete for last issue', () => {
    render(ratingView({
      activeRatingThread: {
        id: 1, title: 'Saga', format: 'Comic', issues_remaining: 1, total_issues: 10,
        issue_number: '10', next_issue_number: null, reading_progress: 'in_progress',
        queue_position: 0,
        issue_id: 100, next_issue_id: null,
      },
    }))
    expect(screen.getByRole('button', { name: /mark read & complete/i })).toBeInTheDocument()
  })

  it('last issue banner is displayed', () => {
    render(ratingView({
      activeRatingThread: {
        id: 1, title: 'Saga', format: 'Comic', issues_remaining: 1, total_issues: 10,
        issue_number: '10', next_issue_number: null, reading_progress: 'in_progress',
        queue_position: 0,
        issue_id: 100, next_issue_id: null,
      },
    }))
    expect(screen.getByText(/This is the last issue in the series/)).toBeInTheDocument()
  })

  it('rating actions container has sticky class for mobile', () => {
    render(ratingView())
    const actions = screen.getByTestId('rating-actions')
    expect(actions.className).toContain('sticky')
    expect(actions.className).toContain('bottom-0')
  })

  it('save button is disabled while rateIsPending', () => {
    render(ratingView({ rateIsPending: true }))
    const save = screen.getByRole('button', { name: /saving/i })
    expect(save).toBeDisabled()
  })

  it('snooze button is disabled while snoozeIsPending', () => {
    render(ratingView({ snoozeIsPending: true }))
    const snooze = screen.getByRole('button', { name: /snoozing/i })
    expect(snooze).toBeDisabled()
  })

  it('cancel button is disabled while dismissIsPending', () => {
    render(ratingView({ dismissIsPending: true }))
    const cancel = screen.getByRole('button', { name: /cancel roll/i })
    expect(cancel).toBeDisabled()
  })

  it('invokes callbacks on save, snooze, and cancel', async () => {
    const onUpdateRating = vi.fn()
    const onSubmitRating = vi.fn()
    const onSnooze = vi.fn()
    const onCancel = vi.fn()
    const user = userEvent.setup()
    render(ratingView({ onUpdateRating, onSubmitRating, onSnooze, onCancel }))

    fireEvent.change(screen.getByRole('slider'), { target: { value: '4' } })
    expect(onUpdateRating).toHaveBeenCalledWith('4')

    await user.click(screen.getByRole('button', { name: /mark read & save/i }))
    expect(onSubmitRating).toHaveBeenCalledWith(false)

    await user.click(screen.getByRole('button', { name: /snooze/i }))
    expect(onSnooze).toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: /cancel roll/i }))
    expect(onCancel).toHaveBeenCalled()
  })

  it('keyboard range input is accessible', () => {
    render(ratingView())
    const slider = screen.getByRole('slider')
    expect(slider).toHaveAttribute('min', '0.5')
    expect(slider).toHaveAttribute('max', '5.0')
    expect(slider).toHaveAttribute('step', '0.5')
    expect(slider).toHaveAttribute('aria-label', 'Rating from 0.5 to 5.0 in steps of 0.5')
  })

  it('shows error message when present', () => {
    render(ratingView({ errorMessage: 'Network error' }))
    expect(screen.getByRole('alert')).toHaveTextContent('Network error')
  })

  it('rating value display reflects current rating', () => {
    render(ratingView({ rating: 4.5 }))
    expect(screen.getByText('4.5')).toBeInTheDocument()
  })

  it('high rating uses amber color', () => {
    render(ratingView({ rating: 4.0 }))
    const value = screen.getByText('4.0')
    expect(value.className).toContain('text-amber-500')
  })

  it('low rating uses red color', () => {
    render(ratingView({ rating: 2.0 }))
    const value = screen.getByText('2.0')
    expect(value.className).toContain('text-red-600')
  })
})

describe('RatingView desktop layout contract (#2711 revises #1943)', () => {
  it('uses a two-column grid without reserving a middle column for removed surfaces', () => {
    const { container } = render(ratingView())
    const grid = container.querySelector('[data-testid="rating-pillars-grid"]')
    expect(grid).not.toBeNull()
    expect(grid!.className).toContain('grid')
    expect(grid!.className).toContain('items-start')
    expect(grid!.className).toContain('lg:grid-cols-2')
    expect(grid!.className).not.toContain('xl:grid-cols-[repeat(auto-fit')
    expect(grid!.className).not.toMatch(/minmax\(0,\d+fr\)/)
    expect(screen.queryByTestId('reading-context-button')).not.toBeInTheDocument()
    expect(screen.queryByTestId('rating-region-reading-optional')).not.toBeInTheDocument()
  })

  it('keeps region cards content-sized instead of stretching to equal-height rows', () => {
    const { container } = render(ratingView())
    const grid = container.querySelector('[data-testid="rating-pillars-grid"]')
    expect(grid!.className).toContain('items-start')
    for (const testId of ['rating-region-comic', 'rating-region-decision']) {
      expect(container.querySelector(`[data-testid="${testId}"]`)!.className).toContain('min-w-0')
    }
  })

  it('avoids fixed grid-row/grid-column placement that reserves holes when regions shrink', () => {
    const { container } = render(ratingView())
    const grid = container.querySelector<HTMLElement>('[data-testid="rating-pillars-grid"]')
    expect(grid).not.toBeNull()
    const cells = Array.from(grid!.querySelectorAll<HTMLDivElement>(':scope > div'))
    expect(cells.length).toBe(2)
    for (const cell of cells) {
      expect(cell.className).not.toMatch(/\b(?:md:|xl:)?(?:col-start|row-start|col-end|row-end|row-span)-\d+\b/)
      expect(cell.className).not.toContain('md:row-span-2')
    }
  })

  it('stacks the decision card and context disclosure in the decision region', () => {
    const { container } = render(ratingView({ readerContext: populatedReaderContext }))
    const decisionRegion = container.querySelector<HTMLElement>('[data-testid="rating-region-decision"]')
    const decisionCard = container.querySelector<HTMLElement>('[data-testid="decision-card"]')
    const contextDisclosure = container.querySelector<HTMLElement>('[data-testid="context-disclosure"]')
    expect(decisionRegion).not.toBeNull()
    expect(decisionCard).not.toBeNull()
    expect(contextDisclosure).not.toBeNull()
    expect(decisionRegion!.contains(decisionCard)).toBe(true)
    expect(decisionRegion!.contains(contextDisclosure)).toBe(true)
    expect(decisionCard!.className).not.toContain('xl:col-span-full')
  })

  it('does not render Reading Context pillar when empty - rating form follows The Comic directly without removed surfaces', () => {
    const { container } = render(ratingView())
    expect(screen.queryByTestId('reading-context-button')).not.toBeInTheDocument()
    expect(screen.queryByTestId('rating-region-reading-context')).not.toBeInTheDocument()
    expect(screen.queryByText('Your Context')).not.toBeInTheDocument()
    const grid = container.querySelector('[data-testid="rating-pillars-grid"]')
    const text = grid!.textContent ?? ''
    expect(text.indexOf('The Comic')).toBeGreaterThan(-1)
    expect(text.indexOf('Your rating')).toBeGreaterThan(-1)
    expect(text.indexOf('The Comic')).toBeLessThan(text.indexOf('Your rating'))
    expect(text).not.toMatch(/\b0[123]\b/)
    expect(text).not.toContain('Reading Context')
    expect(text).not.toContain('Reading Boundaries')
    expect(text).not.toContain('Why this?')
  })

  it('contains no Why this?, Reading Context or Reading Boundaries affordance even with populated props', () => {
    const { container } = render(ratingView({ readerContext: { issue_id: 100, series: { identity_source: 'comicvine', canonical_series_id: 's1', series_name: 'Saga', average_rating: 4, ratings_count: 1, previous_issue: null, recent_ratings: [], highest_rating: 5, lowest_rating: 1 }, crossovers: [], local_chain: { issues: [], edges: [] } } as any }))
    expect(screen.queryByText('Why this?')).not.toBeInTheDocument()
    expect(screen.queryByText('Reading Context')).not.toBeInTheDocument()
    expect(screen.queryByText('Reading Boundaries')).not.toBeInTheDocument()
    expect(container.querySelector('[data-testid="rating-pillars-grid"]')!.className).toContain('lg:grid-cols-2')
  })
})