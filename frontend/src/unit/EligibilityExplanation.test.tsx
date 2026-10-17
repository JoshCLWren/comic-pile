import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { expect, it } from 'vitest'
import { EligibilityExplanation } from '../components/EligibilityExplanation'

it('shows a backend reason without inventing a prerequisite when no source exists', () => {
  render(<MemoryRouter><EligibilityExplanation isBlocked reasons={['No available unread issue']} /></MemoryRouter>)
  expect(screen.getByText('Waiting')).toBeVisible()
  expect(screen.getByText('No available unread issue')).toBeVisible()
  expect(screen.queryByRole('link')).not.toBeInTheDocument()
  expect(screen.queryByText(/requirements are unavailable/)).not.toBeInTheDocument()
})

it('does not duplicate a reason already represented by a named issue link', () => {
  const reason = 'Hold in Ultimate: waiting on One Year In #1'
  render(<MemoryRouter><EligibilityExplanation isBlocked reasons={[reason, 'Another list also blocks this issue']} dependencies={[
    { issue_id: 44, thread_id: 4, thread_title: 'One Year In', issue_number: '1', label: reason },
  ]} /></MemoryRouter>)
  expect(screen.getAllByText(reason)).toHaveLength(1)
  expect(screen.getByText('Another list also blocks this issue')).toBeVisible()
  expect(screen.getByRole('link')).toHaveAttribute('href', '/thread/4?issue=44#issue-44')
})

it('retains useful legacy thread links when an exact source issue is unavailable', () => {
  render(<MemoryRouter><EligibilityExplanation isBlocked dependencies={[
    { thread_id: 9, thread_title: 'Prequel', issue_number: '2', label: 'Blocked by Prequel: #2' },
  ]} /></MemoryRouter>)
  expect(screen.getByRole('link', { name: 'Open Prequel' })).toHaveAttribute('href', '/thread/9')
})

it('distinguishes completed from missing-explanation and available states', () => {
  const { rerender } = render(<EligibilityExplanation isBlocked={false} emptyLabel="Every issue is read" />)
  expect(screen.getByText('Every issue is read')).toBeVisible()
  expect(screen.queryByRole('list')).not.toBeInTheDocument()
  rerender(<EligibilityExplanation isBlocked />)
  expect(screen.getByText(/Reading requirements are unavailable/)).toBeVisible()
  rerender(<EligibilityExplanation isBlocked={false} />)
  expect(screen.getByText('Available now')).toBeVisible()
  expect(screen.queryByText(/Reading requirements are unavailable/)).not.toBeInTheDocument()
})
