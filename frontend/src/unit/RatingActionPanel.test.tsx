import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { RatingActionPanel } from '../pages/RollPage/components/RatingActionPanel'

function renderPanel(onSkip?: () => void, skipIsPending = false) {
  return render(
    <RatingActionPanel
      errorMessage=""
      rateIsPending={false}
      snoozeIsPending={false}
      dismissIsPending={false}
      skipIsPending={skipIsPending}
      issuesRemaining={2}
      onSubmitRating={() => {}}
      onSnooze={() => {}}
      onSkip={onSkip}
      onCancel={() => {}}
    />,
  )
}

describe('RatingActionPanel', () => {
  it('renders skip button when onSkip is provided', () => {
    renderPanel(() => {})
    expect(screen.getByTestId('skip-roll')).toBeInTheDocument()
  })

  it('shows skipping state when skipIsPending is true', () => {
    renderPanel(() => {}, true)
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
    renderPanel(() => {}, true)
    expect(screen.getByTestId('skip-roll')).toBeDisabled()
  })

  it('opens a confirmation warning without calling onSkip when skip is pressed', async () => {
    const user = userEvent.setup()
    const onSkip = vi.fn()
    renderPanel(onSkip)
    expect(screen.queryByTestId('skip-confirm-dialog')).not.toBeInTheDocument()

    await user.click(screen.getByTestId('skip-roll'))

    expect(onSkip).not.toHaveBeenCalled()
    expect(screen.getByTestId('skip-confirm-dialog')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /skip comic/i })).toBeInTheDocument()
    expect(
      screen.getByText((content) => content.includes('Skip moves past this rolled comic')),
    ).toBeInTheDocument()
  })

  it('leaves the roll unchanged when the confirmation is canceled', async () => {
    const user = userEvent.setup()
    const onSkip = vi.fn()
    renderPanel(onSkip)

    await user.click(screen.getByTestId('skip-roll'))
    await user.click(screen.getByTestId('skip-cancel'))

    expect(onSkip).not.toHaveBeenCalled()
    expect(screen.queryByTestId('skip-confirm-dialog')).not.toBeInTheDocument()
  })

  it('closing the warning via its close button leaves the roll unchanged', async () => {
    const user = userEvent.setup()
    const onSkip = vi.fn()
    renderPanel(onSkip)

    await user.click(screen.getByTestId('skip-roll'))
    await user.click(screen.getByRole('button', { name: /close modal/i }))

    expect(onSkip).not.toHaveBeenCalled()
    expect(screen.queryByTestId('skip-confirm-dialog')).not.toBeInTheDocument()
  })

  it('executes exactly one skip mutation when the warning is confirmed', async () => {
    const user = userEvent.setup()
    const onSkip = vi.fn()
    renderPanel(onSkip)

    await user.click(screen.getByTestId('skip-roll'))
    await user.click(screen.getByTestId('skip-confirm'))

    expect(onSkip).toHaveBeenCalledTimes(1)
    expect(screen.queryByTestId('skip-confirm-dialog')).not.toBeInTheDocument()
  })

  it('dismissing the warning with Escape leaves the roll unchanged', async () => {
    const user = userEvent.setup()
    const onSkip = vi.fn()
    renderPanel(onSkip)

    await user.click(screen.getByTestId('skip-roll'))
    await user.keyboard('{Escape}')

    expect(onSkip).not.toHaveBeenCalled()
    expect(screen.queryByTestId('skip-confirm-dialog')).not.toBeInTheDocument()
  })

  it('leaves the snooze and cancel-roll handlers unchanged next to the skip boundary', async () => {
    const user = userEvent.setup()
    const onSnooze = vi.fn()
    const onCancel = vi.fn()
    render(
      <RatingActionPanel
        errorMessage=""
        rateIsPending={false}
        snoozeIsPending={false}
        dismissIsPending={false}
        skipIsPending={false}
        issuesRemaining={2}
        onSubmitRating={() => {}}
        onSnooze={onSnooze}
        onSkip={() => {}}
        onCancel={onCancel}
      />,
    )

    await user.click(screen.getByRole('button', { name: /snooze/i }))
    await user.click(screen.getByRole('button', { name: /cancel roll/i }))

    expect(onSnooze).toHaveBeenCalledTimes(1)
    expect(onCancel).toHaveBeenCalledTimes(1)
  })

  it('keeps the destructive confirm labeled with the pending skip state', async () => {
    const user = userEvent.setup()
    const onSkip = vi.fn()
    const { rerender } = renderPanel(onSkip)

    await user.click(screen.getByTestId('skip-roll'))
    rerender(
      <RatingActionPanel
        errorMessage=""
        rateIsPending={false}
        snoozeIsPending={false}
        dismissIsPending={false}
        skipIsPending={true}
        issuesRemaining={2}
        onSubmitRating={() => {}}
        onSnooze={() => {}}
        onSkip={onSkip}
        onCancel={() => {}}
      />,
    )
    expect(screen.getByTestId('skip-confirm')).toBeDisabled()
    expect(screen.getByTestId('skip-cancel')).toBeDisabled()
  })
})
