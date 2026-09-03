import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { RatingActionPanel } from '../pages/RollPage/components/RatingActionPanel'

describe('RatingActionPanel', () => {
  it('renders skip button when onSkip is provided', () => {
    render(
      <RatingActionPanel
        errorMessage=""
        rateIsPending={false}
        snoozeIsPending={false}
        dismissIsPending={false}
        skipIsPending={false}
        issuesRemaining={2}
        onSubmitRating={() => {}}
        onSnooze={() => {}}
        onSkip={() => {}}
        onCancel={() => {}}
      />,
    )
    expect(screen.getByTestId('skip-roll')).toBeInTheDocument()
  })

  it('shows skipping state when skipIsPending is true', () => {
    render(
      <RatingActionPanel
        errorMessage=""
        rateIsPending={false}
        snoozeIsPending={false}
        dismissIsPending={false}
        skipIsPending={true}
        issuesRemaining={2}
        onSubmitRating={() => {}}
        onSnooze={() => {}}
        onSkip={() => {}}
        onCancel={() => {}}
      />,
    )
    expect(screen.getByText('Skipping…')).toBeInTheDocument()
  })

  it('does not render skip button when onSkip is undefined', () => {
    render(
      <RatingActionPanel
        errorMessage=""
        rateIsPending={false}
        snoozeIsPending={false}
        dismissIsPending={false}
        issuesRemaining={2}
        onSubmitRating={() => {}}
        onSnooze={() => {}}
        onCancel={() => {}}
      />,
    )
    expect(screen.queryByTestId('skip-roll')).not.toBeInTheDocument()
  })

  it('disables skip button when skipIsPending', () => {
    render(
      <RatingActionPanel
        errorMessage=""
        rateIsPending={false}
        snoozeIsPending={false}
        dismissIsPending={false}
        skipIsPending={true}
        issuesRemaining={2}
        onSubmitRating={() => {}}
        onSnooze={() => {}}
        onSkip={() => {}}
        onCancel={() => {}}
      />,
    )
    expect(screen.getByTestId('skip-roll')).toBeDisabled()
  })

  it('invokes onSkip when skip button is clicked', async () => {
    const user = userEvent.setup()
    const onSkip = vi.fn()
    render(
      <RatingActionPanel
        errorMessage=""
        rateIsPending={false}
        snoozeIsPending={false}
        dismissIsPending={false}
        skipIsPending={false}
        issuesRemaining={2}
        onSubmitRating={() => {}}
        onSnooze={() => {}}
        onSkip={onSkip}
        onCancel={() => {}}
      />,
    )
    await user.click(screen.getByTestId('skip-roll'))
    expect(onSkip).toHaveBeenCalledTimes(1)
  })
})
