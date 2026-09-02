import { render, screen } from '@testing-library/react'
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
})
