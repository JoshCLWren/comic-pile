import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { RatingView } from '../pages/RollPage/components/RatingView'

vi.mock('../components/LazyDice3D', () => ({ default: () => <div data-testid="dice" /> }))
vi.mock('../components/Tooltip', () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))
vi.mock('../components/IssueCorrectionDialog', () => ({ default: () => null }))
vi.mock('../pages/RollPage/components/ReadingOrderGroups', () => ({
  ReadingOrderGroups: () => null,
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
      hasValidRolledResult
      poolSize={6}
      errorMessage=""
      rateIsPending={false}
      snoozeIsPending={false}
      dismissIsPending={false}
      readingOrders={[]}
      connectedThreads={[]}
      {...callbacks}
    />,
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
    await user.click(screen.getByRole('button', { name: 'Copy Ultimate X-Men 12' }))

    expect(writeText).toHaveBeenCalledWith('Ultimate X-Men 12')
    expect(screen.getByText('Copied')).toBeInTheDocument()
  })

  it('shows a failure state when clipboard writing fails', async () => {
    const user = userEvent.setup()
    vi.spyOn(navigator.clipboard, 'writeText').mockRejectedValue(new Error('clipboard denied'))

    renderRatingView()
    await user.click(screen.getByRole('button', { name: 'Copy Ultimate X-Men 12' }))

    expect(screen.getByText('Copy failed')).toBeInTheDocument()
  })
})
