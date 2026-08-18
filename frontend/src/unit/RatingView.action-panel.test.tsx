import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { RatingView } from '../pages/RollPage/components/RatingView'
import { RATING_THRESHOLD } from '../pages/RollPage/utils'

vi.mock('../components/LazyDice3D', () => ({ default: () => <div data-testid="dice" /> }))
vi.mock('../components/Tooltip', () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))
vi.mock('../components/IssueCorrectionDialog', () => ({ default: () => null }))
vi.mock('../components/ContinuityCorrectionDialog', () => ({ default: () => null }))
vi.mock('../pages/RollPage/components/ReadingOrderGroups', () => ({
  ReadingOrderGroups: () => null,
}))
vi.mock('../pages/RollPage/components/ContinuityReadinessSummary', () => ({
  ContinuityReadinessSummary: () => null,
}))
vi.mock('../pages/RollPage/components/ComicVineIssueCard', () => ({
  ComicVineIssueCard: () => null,
}))
vi.mock('../pages/RollPage/components/ReadingRouteExplanation', () => ({
  ReadingRouteExplanation: () => null,
}))

function ratingView(overrides: Record<string, unknown> = {}) {
  const defaults = {
    activeRatingThread: {
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
    },
    currentDie: 6,
    rolledResult: 3,
    rating: 3.0,
    predictedDie: 8,
    hasValidRolledResult: true,
    poolSize: 6,
    errorMessage: '',
    rateIsPending: false,
    snoozeIsPending: false,
    dismissIsPending: false,
    readingOrders: [],
    connectedThreads: [],
    onUpdateRating: vi.fn(),
    onSubmitRating: vi.fn(),
    onSnooze: vi.fn(),
    onCancel: vi.fn(),
    onRefreshThread: vi.fn(),
    ...overrides,
  }
  return <RatingView {...defaults} />
}

describe('RatingView action panel (issue #1406)', () => {
  it('Cancel uses semantic danger/cancel styling', () => {
    render(ratingView())
    const cancel = screen.getByRole('button', { name: /cancel roll/i })
    expect(cancel.className).toContain('border-rose-600/30')
    expect(cancel.className).toContain('bg-rose-600/10')
    expect(cancel.className).toContain('text-rose-400')
    expect(cancel.className).toContain('hover:bg-rose-600/20')
    expect(cancel.className).toContain('focus:ring-rose-500')
  })

  it('Snooze remains neutral styling', () => {
    render(ratingView())
    const snooze = screen.getByRole('button', { name: /snooze/i })
    expect(snooze.className).toContain('border-white/10')
    expect(snooze.className).toContain('bg-white/5')
    expect(snooze.className).toContain('text-stone-300')
  })

  it('Snooze and Cancel are equal width (both flex-1)', () => {
    render(ratingView())
    const snooze = screen.getByRole('button', { name: /snooze/i })
    const cancel = screen.getByRole('button', { name: /cancel roll/i })
    expect(snooze.className).toContain('flex-1')
    expect(cancel.className).toContain('flex-1')
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
    render(ratingView({ issues_remaining: 5 }))
    expect(screen.getByRole('button', { name: /mark read & save/i })).toBeInTheDocument()
  })

  it('primary action shows Mark read & complete for last issue', () => {
    render(ratingView({
      activeRatingThread: {
        id: 1, title: 'Saga', format: 'Comic', issues_remaining: 1, total_issues: 10,
        issue_number: '10', next_issue_number: null, reading_progress: 'in_progress',
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
        issue_id: 100, next_issue_id: null,
      },
    }))
    expect(screen.getByText(/This is the last issue in the thread/)).toBeInTheDocument()
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

describe('RatingView three-pillar responsive contract (issue #1402)', () => {
  it('composes the pillar grid as 1 column mobile, 2 columns md, 26/46/28 at xl', () => {
    const { container } = render(ratingView())
    const grid = container.querySelector('[data-testid="rating-pillars-grid"]')
    expect(grid).not.toBeNull()
    expect(grid!.className).toContain('grid')
    expect(grid!.className).toContain('md:grid-cols-2')
    expect(grid!.className).toContain('xl:grid-cols-[minmax(0,26fr)_minmax(0,46fr)_minmax(0,28fr)]')
  })

  it('spans The Comic across both rows at md so Your Context sits below Reading Context on the right', () => {
    const { container } = render(ratingView())
    const comicWrapper = container.querySelector('[data-testid="rating-pillars-grid"] > div')
    expect(comicWrapper).not.toBeNull()
    expect(comicWrapper!.className).toContain('md:row-span-2')
    expect(comicWrapper!.className).toContain('xl:row-span-1')
  })

  it('keeps the three pillars in DOM order Comic, Reading Context, Your Context', () => {
    const { container } = render(ratingView())
    const grid = container.querySelector('[data-testid="rating-pillars-grid"]')
    const headings = Array.from(grid!.querySelectorAll('span'))
      .filter((el) => /01|02|03/.test(el.textContent ?? ''))
      .map((el) => (el.textContent ?? '').trim())
    expect(headings.join(' ')).toContain('01')
    expect(headings.join(' ')).toContain('02')
    expect(headings.join(' ')).toContain('03')
  })
})
