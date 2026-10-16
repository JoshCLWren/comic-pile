import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import { RatingHistoryChart } from '../components/RatingHistoryChart'
import type { CreatorIssueRow } from '../services/api-creators'

const makeRow = (overrides: Partial<CreatorIssueRow> = {}): CreatorIssueRow => ({
  issue_id: 1,
  issue_number: '1',
  thread_id: 1,
  thread_title: 'Series',
  status: 'read',
  roles: ['writer'],
  effective_rating: 4,
  rating_timestamp: '2025-01-01T00:00:00Z',
  sort_key: '1',
  ...overrides,
})

describe('RatingHistoryChart', () => {
  it('renders empty state when no rated issues', () => {
    render(<RatingHistoryChart ratedIssues={[]} />)
    expect(screen.getByText(/No rating history available/)).toBeInTheDocument()
  })

  it('renders chart with rated issues', () => {
    const issues: CreatorIssueRow[] = [
      makeRow({ issue_id: 1, effective_rating: 3, rating_timestamp: '2025-01-01T00:00:00Z' }),
      makeRow({ issue_id: 2, effective_rating: 4, rating_timestamp: '2025-02-01T00:00:00Z' }),
    ]
    render(<RatingHistoryChart ratedIssues={issues} />)
    expect(screen.getByText('2 ratings')).toBeInTheDocument()
    expect(screen.getByText('Individual rating')).toBeInTheDocument()
  })

  it('filters out unrated issues', () => {
    const issues: CreatorIssueRow[] = [
      makeRow({ issue_id: 1, effective_rating: null, rating_timestamp: null }),
      makeRow({ issue_id: 2, effective_rating: 5, rating_timestamp: '2025-03-01T00:00:00Z' }),
    ]
    render(<RatingHistoryChart ratedIssues={issues} />)
    expect(screen.getByText('1 rating')).toBeInTheDocument()
  })
})
