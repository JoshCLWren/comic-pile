import { render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { ReadingContextPillar } from '../pages/RollPage/components/ReadingContextPillar'
import type { ReaderContextResponse } from '../types'

vi.mock('../services/api-issues', () => ({
  issuesApi: {
    getReaderContext: vi.fn(),
  },
}))
vi.mock('../pages/RollPage/components/ReadingOrderGroups', () => ({
  ReadingOrderGroups: () => null,
}))

import { issuesApi } from '../services/api-issues'

const ratingThread = {
  id: 7,
  title: 'Animal Man / Swamp Thing',
  format: 'Comic',
  issues_remaining: 3,
  queue_position: 1,
  total_issues: null,
  reading_progress: null,
  issue_id: 101,
  issue_number: '2',
  next_issue_id: 102,
  next_issue_number: '3',
  last_rolled_result: null,
}

const baseContext: ReaderContextResponse = {
  issue_id: 101,
  series: {
    identity_source: 'unavailable',
    canonical_series_id: null,
    series_name: null,
    average_rating: null,
    ratings_count: 0,
    previous_issue: null,
    recent_ratings: [],
    highest_rating: null,
    lowest_rating: null,
  },
  crossovers: [],
  local_chain: {
    issues: [
      {
        issue_id: 101,
        issue_number: '2',
        position: 2,
        status: 'unread',
        relation: 'current',
        rating: null,
        crossover_memberships: [],
      },
    ],
    edges: [],
  },
}

function renderPillar(context: ReaderContextResponse) {
  vi.mocked(issuesApi.getReaderContext).mockResolvedValue(context)
  return render(
    <MemoryRouter>
      <ReadingContextPillar
        activeRatingThread={ratingThread}
        readingOrders={[]}
        connectedThreads={[]}
        onRefreshThread={vi.fn()}
        rolledResult={null}
        currentDie={6}
      />
    </MemoryRouter>,
  )
}

describe('ReadingContextPillar thread-level crossover', () => {
  it('shows a thread-level membership under Current Issue Crossovers and never renders #?', async () => {
    const context: ReaderContextResponse = {
      ...baseContext,
      crossovers: [
        {
          id: 55,
          name: 'Swamp Thing AUDIT-TEST',
          applies_to_current_issue: true,
          membership_kind: 'thread',
          next_member: null,
          average_rating: null,
          ratings_count: 0,
          read_count: 0,
        },
      ],
      local_chain: {
        issues: [
          {
            issue_id: 101,
            issue_number: '2',
            position: 2,
            status: 'unread',
            relation: 'current',
            rating: null,
            crossover_memberships: [
              { id: 55, name: 'Swamp Thing AUDIT-TEST' },
            ],
          },
        ],
        edges: [],
      },
    }

    renderPillar(context)

    await waitFor(() =>
      expect(screen.getByText('Swamp Thing AUDIT-TEST')).toBeInTheDocument(),
    )
    expect(screen.getByText(/Current Issue Crossovers/i)).toBeInTheDocument()
    expect(screen.queryByText('#?')).not.toBeInTheDocument()
  })

  it('renders words instead of #? when an upcoming crossover cannot resolve a member', async () => {
    const context: ReaderContextResponse = {
      ...baseContext,
      crossovers: [
        {
          id: 56,
          name: 'Moving Thread Crossover',
          applies_to_current_issue: false,
          membership_kind: 'thread',
          next_member: null,
          average_rating: null,
          ratings_count: 0,
          read_count: 0,
        },
      ],
    }

    renderPillar(context)

    await waitFor(() =>
      expect(screen.getByText('Moving Thread Crossover')).toBeInTheDocument(),
    )
    expect(screen.queryByText('#?')).not.toBeInTheDocument()
    expect(
      screen.getByText(/issue unknown — membership covers a moving thread/i),
    ).toBeInTheDocument()
  })
})
