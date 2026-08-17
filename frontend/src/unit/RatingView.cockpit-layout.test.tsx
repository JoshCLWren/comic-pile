import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { RatingView } from '../pages/RollPage/components/RatingView'

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
vi.mock('../hooks/useContinuityReadiness', () => ({
  useContinuityReadiness: () => ({
    readiness: null,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  }),
}))

const callbacks = {
  onUpdateRating: vi.fn(),
  onSubmitRating: vi.fn(),
  onSnooze: vi.fn(),
  onCancel: vi.fn(),
  onRefreshThread: vi.fn(),
}

function renderRatingView(overrides: Record<string, unknown> = {}) {
  const defaults = {
    activeRatingThread: {
      id: 1,
      title: 'Saga',
      format: 'Comic',
      issues_remaining: 5,
      total_issues: 10,
      issue_number: '3',
      next_issue_number: '4',
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
    ...callbacks,
    ...overrides,
  }
  return render(
    <MemoryRouter>
      <RatingView {...defaults} />
    </MemoryRouter>,
  )
}

describe('Three-pillar cockpit layout', () => {
  it('renders three pillar sections with numbered headers', () => {
    renderRatingView()
    expect(screen.getByText('01')).toBeInTheDocument()
    expect(screen.getByText('The Comic')).toBeInTheDocument()
    expect(screen.getByText('02')).toBeInTheDocument()
    expect(screen.getByText('Reading Context')).toBeInTheDocument()
    expect(screen.getByText('03')).toBeInTheDocument()
    expect(screen.getByText('Your Context')).toBeInTheDocument()
  })

  it('uses a responsive grid container', () => {
    const { container } = renderRatingView()
    const grid = container.querySelector('.grid')
    expect(grid).toBeInTheDocument()
    expect(grid?.className).toContain('grid-cols-1')
    expect(grid?.className).toContain('md:grid-cols-2')
    expect(grid?.className).toContain('xl:grid-cols-[26fr_46fr_28fr]')
  })

  it('Comic pillar shows thread title and issue number', () => {
    renderRatingView()
    expect(screen.getByText('Saga')).toBeInTheDocument()
    expect(screen.getByText('#4')).toBeInTheDocument()
  })

  it('Comic pillar shows progress metadata', () => {
    renderRatingView()
    expect(screen.getByText('Issue 4 of 10')).toBeInTheDocument()
    expect(screen.getByText('5 left')).toBeInTheDocument()
  })

  it('Comic pillar shows Copy and Edit buttons', () => {
    renderRatingView()
    expect(screen.getByRole('button', { name: /copy saga 4/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /correct issue number/i })).toBeInTheDocument()
  })

  it('Reading Context pillar shows connected threads', () => {
    renderRatingView({
      connectedThreads: [
        { thread_id: 99, title: 'X-Men', connection_type: 'blocks', dependency_id: 12 },
      ],
    })
    expect(screen.getByText('Verified dependency connections')).toBeInTheDocument()
    expect(screen.getByText('X-Men')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /correct continuity/i })).toBeInTheDocument()
  })

  it('Reading Context pillar shows reading routes', () => {
    renderRatingView({
      readingOrders: [
        {
          id: 1,
          name: 'Main continuity',
          total_items: 10,
          completed_items: 4,
        } as never,
      ],
    })
    expect(screen.getByText('Reading routes')).toBeInTheDocument()
    expect(screen.getByText('Main continuity')).toBeInTheDocument()
    expect(screen.getByText('4/10')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /explain why/i })).toBeInTheDocument()
  })

  it('Your Context pillar shows rating slider', () => {
    renderRatingView()
    expect(screen.getByText('Your rating')).toBeInTheDocument()
    expect(screen.getByText('3.0')).toBeInTheDocument()
    expect(screen.getByRole('slider')).toBeInTheDocument()
  })

  it('Your Context pillar shows die consequence', () => {
    renderRatingView({ currentDie: 6, predictedDie: 4 })
    expect(screen.getByText('d6 → d4')).toBeInTheDocument()
    expect(screen.getByText('More focused next roll')).toBeInTheDocument()
  })

  it('Your Context pillar shows action buttons', () => {
    renderRatingView()
    expect(screen.getByRole('button', { name: /mark read & save/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /snooze/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /cancel roll/i })).toBeInTheDocument()
  })

  it('rating actions container has sticky class for mobile', () => {
    renderRatingView()
    const actions = screen.getByTestId('rating-actions')
    expect(actions.className).toContain('sticky')
    expect(actions.className).toContain('bottom-0')
  })

  it('rating actions go static on desktop', () => {
    renderRatingView()
    const actions = screen.getByTestId('rating-actions')
    expect(actions.className).toContain('md:static')
  })

  it('shows last-issue banner in Your Context pillar', () => {
    renderRatingView({
      activeRatingThread: {
        id: 1,
        title: 'Saga',
        format: 'Comic',
        issues_remaining: 1,
        total_issues: 10,
        issue_number: '10',
        next_issue_number: null,
        issue_id: 100,
        next_issue_id: null,
      },
    })
    expect(screen.getByText(/This is the last issue in the thread/)).toBeInTheDocument()
  })

  it('shows error message in Your Context pillar', () => {
    renderRatingView({ errorMessage: 'Network error' })
    expect(screen.getByRole('alert')).toHaveTextContent('Network error')
  })

  it('invokes save callback', async () => {
    const onSubmitRating = vi.fn()
    const user = userEvent.setup()
    renderRatingView({ onSubmitRating })
    await user.click(screen.getByRole('button', { name: /mark read & save/i }))
    expect(onSubmitRating).toHaveBeenCalledWith(false)
  })

  it('invokes snooze callback', async () => {
    const onSnooze = vi.fn()
    const user = userEvent.setup()
    renderRatingView({ onSnooze })
    await user.click(screen.getByRole('button', { name: /snooze/i }))
    expect(onSnooze).toHaveBeenCalled()
  })

  it('invokes cancel callback', async () => {
    const onCancel = vi.fn()
    const user = userEvent.setup()
    renderRatingView({ onCancel })
    await user.click(screen.getByRole('button', { name: /cancel roll/i }))
    expect(onCancel).toHaveBeenCalled()
  })

  it('copy button copies thread title and issue number', async () => {
    const user = userEvent.setup()
    const writeText = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue(undefined)
    renderRatingView()
    await user.click(screen.getByRole('button', { name: /copy saga 4/i }))
    expect(writeText).toHaveBeenCalledWith('Saga 4')
  })
})
