import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { RatingView } from '../pages/RollPage/components/RatingView'
vi.mock('../contexts/useToast', () => ({ useToast: () => ({ toasts: [], showToast: vi.fn(), removeToast: vi.fn() }) }))

vi.mock('../components/LazyDice3D', () => ({ default: () => <div data-testid="dice" /> }))
vi.mock('../components/Tooltip', () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))
vi.mock('../components/IssueCorrectionDialog', () => ({ default: () => null }))
vi.mock('../pages/RollPage/components/ReadingOrderGroups', () => ({
  ReadingOrderGroups: () => null,
}))
vi.mock('../hooks/useContinuityReadiness', () => ({
  useContinuityReadiness: () => ({
    readiness: null,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  }),
}))

vi.mock('../hooks/useReaderContext', () => ({
  useReaderContext: () => ({
    context: null,
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

function renderRatingView() {
  render(
    <MemoryRouter>
      <RatingView
        activeRatingThread={{
          id: 1,
          title: 'Ultimate X-Men',
          format: 'Comic',
          issues_remaining: 4,
          total_issues: 12,
          issue_number: '11',
          next_issue_number: '12',
        } as never}
        currentDie={6}
        rolledResult={2}
        rating={4}
        predictedDie={4}
        errorMessage=""
        rateIsPending={false}
        snoozeIsPending={false}
        dismissIsPending={false}
        readingOrders={[]}
        connectedThreads={[]}
        readerContext={null}
        isReaderContextLoading={false}
        readerContextError={null}
        {...callbacks}
      />
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
    expect(screen.getByText('Copied')).toBeInTheDocument()
    expect(copyButton.getAttribute('aria-label')).toBe('Copy Ultimate X-Men 12')
    expect(copyButton.className).toContain('min-h-11')
  })

  it('shows a failure state when clipboard writing fails', async () => {
    const user = userEvent.setup()
    vi.spyOn(navigator.clipboard, 'writeText').mockRejectedValue(new Error('clipboard denied'))

    renderRatingView()
    await user.click(screen.getByRole('button', { name: 'Copy Ultimate X-Men 12' }))

    expect(screen.getByText(/Copy failed/)).toBeInTheDocument()
    expect(screen.getByText('Retry copy')).toBeInTheDocument()
    expect(screen.getByText(/Copy failed/).getAttribute('role')).toBe('status')
  })

  it('is visually colocated with the rating controls on the post-roll surface', async () => {
    renderRatingView()

    const ratingActions = screen.getByTestId('rating-actions')
    const copyRow = screen.getByTestId('copy-title-row')
    const copyButton = within(ratingActions).getByRole('button', { name: 'Copy Ultimate X-Men 12' })

    expect(ratingActions.contains(copyRow)).toBe(true)
    expect(copyRow.contains(copyButton)).toBe(true)
    // The rating actions grid cell wraps the panel; ensures colocation with rating workflow
    const actionsGridCell = screen.getByTestId('rating-actions-grid-cell')
    expect(actionsGridCell.contains(ratingActions)).toBe(true)

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
    expect(screen.getByText('Retry copy')).toBeInTheDocument()

    // Retry succeeds
    vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValueOnce(undefined)
    await user.click(screen.getByRole('button', { name: 'Retry copy' }))
    expect(screen.getByText('Copied')).toBeInTheDocument()
  })
})
