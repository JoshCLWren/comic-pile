import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { RatingView } from '../pages/RollPage/components/RatingView'
import { cast } from '../utils/cast'
import type { RatingViewData } from '../pages/RollPage/useRatingView'
vi.mock('../contexts/useToast', () => ({ useToast: () => ({ toasts: [], showToast: vi.fn(), removeToast: vi.fn() }) }))

vi.mock('../components/LazyDice3D', () => ({ default: () => <div data-testid="dice" /> }))
vi.mock('../components/Tooltip', () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))
vi.mock('../components/IssueCorrectionDialog', () => ({ default: () => null }))
vi.mock('../pages/RollPage/components/ReadingOrderGroups', () => ({
  ReadingOrderGroups: () => null,
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

const callbacks = {
  onUpdateRating: vi.fn(),
  onSubmitRating: vi.fn(),
  onSnooze: vi.fn(),
  onCancel: vi.fn(),
  onRefreshThread: vi.fn(),
}

function makeRatingViewData(overrides: Partial<RatingViewData> = {}): RatingViewData {
  return {
    activeRatingThread: cast<RatingViewData['activeRatingThread']>({
      id: 1,
      title: 'Ultimate X-Men',
      format: 'Comic',
      issues_remaining: 4,
      total_issues: 12,
      issue_number: '11',
      next_issue_number: '12',
    }),
    currentDie: 6,
    rolledResult: 2,
    rating: 4,
    predictedDie: 4,
    errorMessage: '',
    rateIsPending: false,
    snoozeIsPending: false,
    dismissIsPending: false,
    skipIsPending: false,
    onUpdateRating: callbacks.onUpdateRating,
    onSubmitRating: callbacks.onSubmitRating,
    onSnooze: callbacks.onSnooze,
    onSkip: undefined,
    onCancel: callbacks.onCancel,
    onRefreshThread: callbacks.onRefreshThread,
    readerContext: null,
    isReaderContextLoading: false,
    readerContextError: null,
    ratingViewTopRef: null,
    issuesRemaining: 4,
    ...overrides,
  }
}

function renderRatingView() {
  render(
    <MemoryRouter>
      <RatingView data={makeRatingViewData()} />
    </MemoryRouter>,
  )
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('RatingView copy comic reference', () => {
  it('copies the series title and active issue number without a hash', async () => {
    const user = userEvent.setup()
    const writeText = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue(undefined)

    renderRatingView()
    const copyButton = screen.getByRole('button', { name: 'Copy Ultimate X-Men 12' })
    await user.click(copyButton)

    expect(writeText).toHaveBeenCalledWith('Ultimate X-Men 12')
    expect(screen.getByText('COPIED')).toBeInTheDocument()
    expect(copyButton.getAttribute('aria-label')).toBe('Copy Ultimate X-Men 12')
    expect(copyButton.className).toContain('min-h-9')
  })

  it('shows a failure state when clipboard writing fails', async () => {
    const user = userEvent.setup()
    vi.spyOn(navigator.clipboard, 'writeText').mockRejectedValue(new Error('clipboard denied'))

    renderRatingView()
    await user.click(screen.getByRole('button', { name: 'Copy Ultimate X-Men 12' }))

    expect(screen.getByText(/Copy failed/)).toBeInTheDocument()
    expect(screen.getByText('Retry')).toBeInTheDocument()
    expect(screen.getByText(/Copy failed/).getAttribute('role')).toBe('status')
  })

  it('is visually colocated with the rating controls on the post-roll surface', async () => {
    renderRatingView()

    const decisionCard = screen.getByTestId('decision-card')
    const copyButton = within(decisionCard).getByRole('button', { name: 'Copy Ultimate X-Men 12' })
    const ratingActions = screen.getByTestId('rating-actions')

    expect(decisionCard.contains(copyButton)).toBe(true)
    expect(decisionCard.contains(ratingActions)).toBe(true)

    // Old placement in the Comic pillar is removed
    const comicControls = screen.getByTestId('comic-header-controls')
    expect(within(comicControls).queryByRole('button', { name: /Copy/i })).not.toBeInTheDocument()
    expect(comicControls.textContent).not.toMatch(/Copy title/)
  })

  it('remains keyboard accessible and shows retry after failure', async () => {
    const user = userEvent.setup()
    vi.spyOn(navigator.clipboard, 'writeText').mockRejectedValueOnce(new Error('clipboard denied'))

    renderRatingView()
    const copyButton = screen.getByRole('button', { name: 'Copy Ultimate X-Men 12' })

    copyButton.focus()
    expect(document.activeElement).toBe(copyButton)

    await user.keyboard('{Enter}')
    expect(screen.getByText('Retry')).toBeInTheDocument()

    // Retry succeeds — aria-label stays "Copy …" even when button text is "Retry"
    vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValueOnce(undefined)
    await user.click(screen.getByRole('button', { name: 'Copy Ultimate X-Men 12' }))
    expect(screen.getByText('COPIED')).toBeInTheDocument()
  })
})