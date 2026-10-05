import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { RatingView } from '../pages/RollPage/components/RatingView'
import { ToastProvider } from '../contexts/ToastProvider'
import { RATING_THRESHOLD } from '../pages/RollPage/utils'
import type { RatingViewData } from '../pages/RollPage/useRatingView'
import type { ReaderContextResponse } from '../types'

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

const populatedReaderContext: ReaderContextResponse = {
  issue_id: 100,
  series: {
    identity_source: 'comicvine',
    canonical_series_id: 's1',
    series_name: 'Saga',
    average_rating: 4,
    ratings_count: 1,
    previous_issue: null,
    recent_ratings: [],
    highest_rating: 5,
    lowest_rating: 1,
  },
  crossovers: [],
  local_chain: { issues: [], edges: [] },
}

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
    manualDie: null,
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
    readingContextRequested: false,
    readingBoundariesRequested: false,
    readingOrders: [],
    connectedThreads: [],
    onShowContext: vi.fn(),
    onShowBoundaries: vi.fn(),
    readingOrdersIsLoading: false,
    readingOrdersError: null,
    connectedThreadsIsLoading: false,
    connectedThreadsError: null,
    ...overrides,
  }
}

function ratingView(overrides: Partial<RatingViewData> = {}) {
  return (
    <MemoryRouter>
      <ToastProvider>
        <RatingView data={makeRatingViewData(overrides)} />
      </ToastProvider>
    </MemoryRouter>
  )
}

describe('RatingView action panel (issue #1406)', () => {
  it('Cancel uses demoted tertiary styling that does not rival the primary save', () => {
    render(ratingView())
    const cancel = screen.getByRole('button', { name: /cancel roll/i })
    const snooze = screen.getByRole('button', { name: /snooze/i })
    // Issue #3009 replaces Cancel's one-off tertiary treatment with the shared
    // secondary peer class, so the peers are now literally identical rather
    // than merely similar. Cancel used to be the only transparent peer.
    expect(cancel.className).toBe(snooze.className)
    expect(cancel.className).toContain('border-[var(--theme-border)]')
    expect(cancel.className).toContain('bg-[var(--theme-bg-panel)]')
    // Demotion comes from the flat surface, not from an accent fill and not from
    // the primary's uppercase treatment. The old contract also demanded
    // `bg-transparent` plus muted text, which is what introduced the pale-cyan
    // command-center accent the visual grammar forbids for a non-accent meaning.
    expect(cancel.className).not.toMatch(/uppercase/)
    expect(cancel.className).not.toContain('theme-primary-action')
    expect(cancel.className).not.toContain('theme-continuity-accent')
    expect(cancel.className).not.toContain('theme-danger')
    expect(cancel.className).not.toContain('rose')
    expect(cancel.className).not.toContain('focus:ring-rose-500')
  })

  it('Snooze remains neutral styling', () => {
    render(ratingView())
    const snooze = screen.getByRole('button', { name: /snooze/i })
    expect(snooze.className).toContain('border-[var(--theme-border)]')
    expect(snooze.className).toContain('bg-[var(--theme-bg-panel)]')
    // Issue #3009 replaces the raw `text-stone-300` palette utility with the
    // semantic text token so the neutral label stays readable in every theme.
    expect(snooze.className).toContain('text-[var(--theme-text-primary)]')
    expect(snooze.className).not.toMatch(/\bstone-\d/)
    expect(snooze.className).not.toContain('theme-comic-accent')
    expect(snooze.className).not.toContain('theme-danger')
    expect(snooze.className).not.toContain('theme-continuity-accent')
  })

  it('Snooze and Cancel are equal width (both flex-1)', () => {
    render(ratingView())
    const snooze = screen.getByRole('button', { name: /snooze/i })
    const cancel = screen.getByRole('button', { name: /cancel roll/i })
    expect(snooze.className).toContain('flex-1')
    expect(cancel.className).toContain('flex-1')
  })

  it('primary save remains the dominant hierarchy over Cancel (issue #2347, revised by #3009)', () => {
    render(ratingView())
    const save = screen.getByRole('button', { name: /mark read & save/i })
    const cancel = screen.getByRole('button', { name: /cancel roll/i })
    // Issue #3009 moves the dominant affirmative fill off the comic-identity
    // accent and onto the reserved `--theme-primary-action` role. The hierarchy
    // this test protects is unchanged: the primary keeps the solid accent fill,
    // the full row width, and the uppercase treatment that Cancel does not have.
    const primary = save.classList.contains('bg-[var(--theme-primary-action)]')
    const cancelIsDemoted =
      cancel.classList.contains('bg-[var(--theme-bg-panel)]') &&
      !cancel.classList.contains('bg-[var(--theme-primary-action)]')
    expect(primary).toBe(true)
    expect(cancelIsDemoted).toBe(true)
    expect(save.classList.contains('w-full')).toBe(true)
    expect(save.className).toMatch(/uppercase/)
    expect(cancel.className).not.toMatch(/uppercase/)
    expect(cancel.className).not.toContain('rose')
  })

  it('shows dN → dM die consequence', () => {
    render(ratingView({ currentDie: 6, predictedDie: 4 }))
    expect(screen.getByText('d6 → d4')).toBeInTheDocument()
    expect(screen.queryByText('More focused next roll')).not.toBeInTheDocument()
  })

  it('shows step-up consequence for rating below threshold', () => {
    render(ratingView({ currentDie: 6, predictedDie: 8, rating: 3.0 }))
    expect(screen.getByText('d6 → d8')).toBeInTheDocument()
    expect(screen.queryByText('More variety next roll')).not.toBeInTheDocument()
  })

  it('shows step-down consequence for rating at or above threshold', () => {
    render(ratingView({ currentDie: 6, predictedDie: 4, rating: RATING_THRESHOLD }))
    expect(screen.getByText('d6 → d4')).toBeInTheDocument()
    expect(screen.queryByText('More focused next roll')).not.toBeInTheDocument()
  })

  it('shows boundary die same when rating is neutral', () => {
    render(ratingView({ currentDie: 6, predictedDie: 6, rating: 3.0 }))
    expect(screen.getByText('d6 → d6')).toBeInTheDocument()
    expect(screen.queryByText('Die stays the same')).not.toBeInTheDocument()
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

  it('rating actions container does not use sticky/fixed positioning (layout is normal flow)', () => {
    render(ratingView())
    const actions = screen.getByTestId('rating-actions')
    expect(actions.className).not.toContain('sticky')
    expect(actions.className).not.toContain('bottom-0')
    expect(actions.className).toContain('border-t')
    expect(actions.className).toContain('surface-glass')
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

  it('high rating uses personal accent color', () => {
    render(ratingView({ rating: 4.0 }))
    const value = screen.getByText('4.0')
    expect(value.className).toContain('text-[var(--theme-personal-accent)]')
  })

  it('low rating uses danger color', () => {
    render(ratingView({ rating: 1.5 }))
    const value = screen.getByText('1.5')
    expect(value.className).toContain('text-[var(--theme-danger)]')
  })

  it('below-average rating uses warning color', () => {
    render(ratingView({ rating: 2.5 }))
    const value = screen.getByText('2.5')
    expect(value.className).toContain('text-[var(--theme-warning)]')
  })

  it('middling rating uses comic accent color', () => {
    render(ratingView({ rating: 3.5 }))
    const value = screen.getByText('3.5')
    expect(value.className).toContain('text-[var(--theme-comic-accent)]')
  })

  it('perfect rating uses personal accent color', () => {
    render(ratingView({ rating: 5.0 }))
    const value = screen.getByText('5.0')
    expect(value.className).toContain('text-[var(--theme-personal-accent)]')
  })

  it('rating value is the dominant text size', () => {
    render(ratingView({ rating: 4.5 }))
    const value = screen.getByText('4.5')
    expect(value.className).toContain('text-5xl')
  })

  it('slider has rating-slider class for custom styling', () => {
    render(ratingView())
    const slider = screen.getByRole('slider')
    expect(slider.className).toContain('rating-slider')
  })

  it('slider fill reflects the current rating value', () => {
    const { rerender } = render(ratingView({ rating: 0.5 }))
    const slider = screen.getByRole('slider')
    expect(slider.style.getPropertyValue('--slider-fill')).toBe('0%')

    rerender(ratingView({ rating: 5.0 }))
    expect(screen.getByRole('slider').style.getPropertyValue('--slider-fill')).toBe('100%')

    rerender(ratingView({ rating: 2.75 }))
    expect(screen.getByRole('slider').style.getPropertyValue('--slider-fill')).toBe('50%')
  })

  it('secondary actions wrap so peers reflow instead of squeezing on one row (issue #3009)', () => {
    render(ratingView())
    const secondary = screen.getByTestId('rating-secondary-actions')
    // Issue #3009 reverses the earlier single-row requirement: holding all three
    // peers on one non-wrapping row is what squeezed `Cancel roll` against its
    // button edges at supported widths. Wrapping plus a shared minimum width is
    // the reported fix, and rendered containment is covered by the #2350 and
    // #2942 Chromium reflow suites.
    expect(secondary.className).toContain('flex')
    expect(secondary.className).toContain('flex-wrap')
    expect(secondary.className).toContain('gap-2')
  })

  it('secondary action buttons have equal flex weight', () => {
    render(ratingView())
    const snooze = screen.getByRole('button', { name: /snooze/i })
    const cancel = screen.getByRole('button', { name: /cancel roll/i })
    expect(snooze.className).toContain('flex-1')
    expect(cancel.className).toContain('flex-1')
    // Issue #3009 replaces the old "no min width at all" expectation with one
    // shared standard-scale minimum width. The arbitrary `min-w-[7.5rem]` value
    // is still rejected: the visual grammar prefers the standard spacing scale.
    expect(snooze.className).toContain('min-w-28')
    expect(cancel.className).toContain('min-w-28')
    expect(snooze.className).not.toContain('min-w-\\[7.5rem\\]')
    expect(cancel.className).not.toContain('min-w-\\[7.5rem\\]')
  })
})

describe('RatingView desktop layout contract (#2711 revises #1943)', () => {
  it('uses a two-column grid without reserving a middle column for removed surfaces', () => {
    const { container } = render(ratingView())
    const grid = container.querySelector('[data-testid="rating-pillars-grid"]')
    expect(grid).not.toBeNull()
    expect(grid!.className).toContain('grid')
    expect(grid!.className).toContain('items-start')
    expect(grid!.className).toContain('lg:grid-cols-[minmax(0,24rem)_minmax(18rem,24rem)]')
    expect(grid!.className).not.toContain('xl:grid-cols-[repeat(auto-fit')
    expect(grid!.className).toContain('lg:max-w-4xl')
    // #2764: collapsed optional cards live inside the decision region.
    expect(screen.getByTestId('reading-context-button')).toBeInTheDocument()
    expect(screen.getByTestId('rating-region-reading-optional')).toBeInTheDocument()
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

  it('stacks the decision card and optional cards in the decision region', () => {
    const { container } = render(ratingView({ readerContext: populatedReaderContext }))
    const decisionRegion = container.querySelector<HTMLElement>('[data-testid="rating-region-decision"]')
    const decisionCard = container.querySelector<HTMLElement>('[data-testid="decision-card"]')
    const optionalCards = container.querySelector<HTMLElement>('[data-testid="rating-region-reading-optional"]')
    expect(decisionRegion).not.toBeNull()
    expect(decisionCard).not.toBeNull()
    expect(optionalCards).not.toBeNull()
    expect(decisionRegion!.contains(decisionCard)).toBe(true)
    expect(decisionRegion!.contains(optionalCards)).toBe(true)
    expect(decisionCard!.className).not.toContain('xl:col-span-full')
  })

  it('renders collapsed optional cards without expanded pillar content - rating form follows comic region directly', () => {
    const { container } = render(ratingView())
    expect(screen.getByTestId('reading-context-button')).toBeInTheDocument()
    expect(screen.getByTestId('reading-boundaries-button')).toBeInTheDocument()
    expect(screen.queryByTestId('rating-region-reading-context')).not.toBeInTheDocument()
    expect(screen.queryByText('Your Context')).not.toBeInTheDocument()
    const grid = container.querySelector('[data-testid="rating-pillars-grid"]')
    const text = grid!.textContent ?? ''
    // Comic region (first column) contains the thread title "Saga"
    expect(text.indexOf('Saga')).toBeGreaterThan(-1)
    expect(text.indexOf('Your rating')).toBeGreaterThan(-1)
    expect(text.indexOf('Saga')).toBeLessThan(text.indexOf('Your rating'))
    expect(text).not.toMatch(/\b0[123]\b/)
    expect(text).toContain('Reading Context')
    expect(text).toContain('Reading Boundaries')
    expect(text).not.toContain('Why this?')
  })

  it('contains collapsed optional cards but no Why this? even with populated props', () => {
    // SAFETY: the reader-context fixture supplies only the fields the rating panel reads
    const { container } = render(ratingView({ readerContext: { issue_id: 100, series: { identity_source: 'comicvine', canonical_series_id: 's1', series_name: 'Saga', average_rating: 4, ratings_count: 1, previous_issue: null, recent_ratings: [], highest_rating: 5, lowest_rating: 1 }, crossovers: [], local_chain: { issues: [], edges: [] } } as any }))
    expect(screen.queryByText('Why this?')).not.toBeInTheDocument()
    expect(screen.getByTestId('reading-context-button')).toBeInTheDocument()
    expect(screen.getByTestId('reading-boundaries-button')).toBeInTheDocument()
    expect(screen.queryByTestId('reading-context-content')).not.toBeInTheDocument()
    expect(container.querySelector('[data-testid="rating-pillars-grid"]')!.className).toContain('lg:grid-cols-[minmax(0,24rem)_minmax(18rem,24rem)]')
  })
})