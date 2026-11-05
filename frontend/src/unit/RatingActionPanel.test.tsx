import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { RatingActionPanel } from '../pages/RollPage/components/RatingActionPanel'
import { rollSecondaryActionClass } from '../pages/RollPage/actionClasses'

function renderPanel() {
  return render(
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
}

describe('RatingActionPanel', () => {
  it('never renders a skip control: reroll is the only move-past action', () => {
    renderPanel()
    expect(screen.queryByTestId('skip-roll')).not.toBeInTheDocument()
    expect(screen.queryByTestId('skip-confirm-dialog')).not.toBeInTheDocument()
  })

  it('keeps the snooze and cancel-roll handlers next to the retired skip boundary', async () => {
    const user = userEvent.setup()
    const onSnooze = vi.fn()
    const onCancel = vi.fn()
    render(
      <RatingActionPanel
        errorMessage=""
        rateIsPending={false}
        snoozeIsPending={false}
        dismissIsPending={false}
        issuesRemaining={2}
        onSubmitRating={() => {}}
        onSnooze={onSnooze}
        onCancel={onCancel}
      />,
    )

    await user.click(screen.getByRole('button', { name: /snooze/i }))
    await user.click(screen.getByRole('button', { name: /cancel roll/i }))

    expect(onSnooze).toHaveBeenCalledTimes(1)
    expect(onCancel).toHaveBeenCalledTimes(1)
  })

  it('resets Copy title to idle when threadTitle changes', async () => {
    const user = userEvent.setup()
    vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue(undefined)

    const { rerender } = render(
      <RatingActionPanel
        errorMessage=""
        rateIsPending={false}
        snoozeIsPending={false}
        dismissIsPending={false}
        issuesRemaining={2}
        onSubmitRating={() => {}}
        onSnooze={() => {}}
        onCancel={() => {}}
        threadTitle="Cable"
        issueNumber="#62"
      />,
    )

    await user.click(screen.getByRole('button', { name: /copy cable #62/i }))
    expect(screen.getByRole('button', { name: /copy cable #62/i })).toHaveTextContent('Copied')

    rerender(
      <RatingActionPanel
        errorMessage=""
        rateIsPending={false}
        snoozeIsPending={false}
        dismissIsPending={false}
        issuesRemaining={2}
        onSubmitRating={() => {}}
        onSnooze={() => {}}
        onCancel={() => {}}
        threadTitle="Gotham Central"
        issueNumber="#37"
      />,
    )

    expect(screen.getByRole('button', { name: /copy gotham central #37/i })).toHaveTextContent(
      'Copy title',
    )
  })

  it('resets Copy title to idle when issueNumber changes', async () => {
    const user = userEvent.setup()
    vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue(undefined)

    const { rerender } = render(
      <RatingActionPanel
        errorMessage=""
        rateIsPending={false}
        snoozeIsPending={false}
        dismissIsPending={false}
        issuesRemaining={2}
        onSubmitRating={() => {}}
        onSnooze={() => {}}
        onCancel={() => {}}
        threadTitle="Cable"
        issueNumber="#62"
      />,
    )

    await user.click(screen.getByRole('button', { name: /copy cable #62/i }))
    expect(screen.getByRole('button', { name: /copy cable #62/i })).toHaveTextContent('Copied')

    rerender(
      <RatingActionPanel
        errorMessage=""
        rateIsPending={false}
        snoozeIsPending={false}
        dismissIsPending={false}
        issuesRemaining={1}
        onSubmitRating={() => {}}
        onSnooze={() => {}}
        onCancel={() => {}}
        threadTitle="Cable"
        issueNumber="#63"
      />,
    )

    expect(screen.getByRole('button', { name: /copy cable #63/i })).toHaveTextContent('Copy title')
  })

  it('copies the new comic title after reset and shows success feedback', async () => {
    const user = userEvent.setup()
    const writeText = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue(undefined)

    const { rerender } = render(
      <RatingActionPanel
        errorMessage=""
        rateIsPending={false}
        snoozeIsPending={false}
        dismissIsPending={false}
        issuesRemaining={2}
        onSubmitRating={() => {}}
        onSnooze={() => {}}
        onCancel={() => {}}
        threadTitle="Cable"
        issueNumber="#62"
      />,
    )

    await user.click(screen.getByRole('button', { name: /copy cable #62/i }))
    expect(writeText).toHaveBeenCalledWith('Cable #62')

    rerender(
      <RatingActionPanel
        errorMessage=""
        rateIsPending={false}
        snoozeIsPending={false}
        dismissIsPending={false}
        issuesRemaining={1}
        onSubmitRating={() => {}}
        onSnooze={() => {}}
        onCancel={() => {}}
        threadTitle="Gotham Central"
        issueNumber="#37"
      />,
    )

    await user.click(screen.getByRole('button', { name: /copy gotham central #37/i }))
    expect(writeText).toHaveBeenCalledWith('Gotham Central #37')
    expect(screen.getByRole('button', { name: /copy gotham central #37/i })).toHaveTextContent(
      'Copied',
    )
  })

  it('secondaries wrap into roomier lanes via a comfortable min-width instead of compressing', () => {
    renderPanel()
    const secondaryRow = screen.getByTestId('rating-secondary-actions')
    expect(secondaryRow.className).toContain('flex-wrap')
    for (const button of [
      screen.getByRole('button', { name: /snooze/i }),
      screen.getByRole('button', { name: /cancel roll/i }),
    ]) {
      expect(button.className).toContain('min-w-28')
      expect(button.className).toContain('flex-1')
      expect(button.className).toContain('px-4')
    }
  })

  it('every secondary peer shares one identical visual language (issue #3009)', () => {
    renderPanel()
    const shared = rollSecondaryActionClass
    for (const button of [
      screen.getByRole('button', { name: /snooze/i }),
      screen.getByRole('button', { name: /cancel roll/i }),
    ]) {
      expect(button.className).toBe(shared)
    }
  })
})
