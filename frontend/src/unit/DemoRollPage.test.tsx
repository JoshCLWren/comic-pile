import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import DemoRollPage from '../pages/DemoRollPage'
import type { RollResponse } from '../types'

const seededRoll: RollResponse = {
  thread_id: 999,
  title: 'Sample: The Dark Knight Returns (Demo)',
  format: 'comic',
  issues_remaining: 3,
  queue_position: 1,
  die_size: 6,
  result: 4,
  offset: 0,
  snoozed_count: 0,
  issue_id: 1001,
  issue_number: '#4',
  next_issue_id: 1002,
  next_issue_number: '#5',
  total_issues: 12,
  reading_progress: 'Late in arc — the final act is building.',
  explanation: 'Demo roll: seeded sample data, no account state.',
}

function createApi(roll: () => Promise<RollResponse>) {
  return { roll: vi.fn(roll) }
}

function renderPage(api: { roll: () => Promise<RollResponse> }) {
  return render(
    <MemoryRouter>
      <DemoRollPage api={api} />
    </MemoryRouter>,
  )
}

describe('DemoRollPage', () => {
  it('serves the seeded roll to a guest with no account state', async () => {
    const api = createApi(() => Promise.resolve(seededRoll))

    renderPage(api)

    expect(await screen.findByTestId('demo-roll-page')).toBeInTheDocument()
    expect(screen.getByText('Sample: The Dark Knight Returns (Demo)')).toBeInTheDocument()
    expect(screen.getByText(/Sample \/ Demo data/)).toBeInTheDocument()
    expect(api.roll).toHaveBeenCalledTimes(1)
  })

  it('keeps the rating loop ephemeral with no write endpoint', async () => {
    const api = createApi(() => Promise.resolve(seededRoll))

    renderPage(api)

    const slider = await screen.findByTestId('demo-rating-input')
    expect(screen.queryByTestId('demo-rated')).not.toBeInTheDocument()

    fireEvent.change(slider, { target: { value: '4.5' } })

    expect(screen.getByTestId('demo-rating-value')).toHaveTextContent('4.5')
    expect(screen.getByTestId('demo-rated')).toHaveTextContent('Rated 4.5')
    // The page owns exactly one read seam, so a demo rating cannot persist.
    expect(Object.keys(api)).toEqual(['roll'])
    expect(api.roll).toHaveBeenCalledTimes(1)
  })

  it('offers the signup and login conversion CTAs', async () => {
    renderPage(createApi(() => Promise.resolve(seededRoll)))

    expect(await screen.findByTestId('demo-signup-cta')).toHaveAttribute('href', '/register')
    expect(screen.getByTestId('demo-login-cta')).toHaveAttribute('href', '/login')
  })

  it('distinguishes a failed roll and recovers on retry', async () => {
    const api = createApi(() => Promise.resolve(seededRoll))
    api.roll
      .mockRejectedValueOnce(new Error('demo unavailable'))
      .mockResolvedValueOnce(seededRoll)

    renderPage(api)

    expect(await screen.findByTestId('demo-roll-error')).toBeInTheDocument()

    fireEvent.click(screen.getByTestId('demo-retry'))

    expect(await screen.findByTestId('demo-roll-page')).toBeInTheDocument()
    expect(api.roll).toHaveBeenCalledTimes(2)
  })
})
