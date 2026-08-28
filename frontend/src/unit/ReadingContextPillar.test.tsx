import { render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { ReadingContextPillar } from '../pages/RollPage/components/ReadingContextPillar'
import type { ReaderContextResponse } from '../types'

vi.mock('../pages/RollPage/components/ReadingOrderGroups', () => ({
  ReadingOrderGroups: () => null,
}))
vi.mock('../hooks/useContinuityReadiness', () => ({
  useContinuityReadiness: () => ({ readiness: null, isLoading: false, error: null, refetch: vi.fn() }),
}))
vi.mock('../pages/RollPage/components/ReadingPathPanel', () => ({
  ReadingPathPanel: () => null,
}))
vi.mock('../pages/RollPage/components/ContinuityReadinessSummary', () => ({
  ContinuityReadinessSummary: () => null,
}))

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
  return render(
    <MemoryRouter>
      <ReadingContextPillar
        activeRatingThread={ratingThread}
        readingOrders={[]}
        connectedThreads={[]}
        onRefreshThread={vi.fn()}
        rolledResult={null}
        currentDie={6}
        readerContext={context}
        isReaderContextLoading={false}
        readerContextError={null}
      />
    </MemoryRouter>,
  )
}

describe('ReadingContextPillar dependency and continuity edges', () => {
  it('renders dependency and continuity edges when present', async () => {
    const context: ReaderContextResponse = {
      ...baseContext,
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
        edges: [
          {
            id: 11,
            kind: 'dependency',
            source_issue_id: 98,
            target_issue_id: 101,
            source_thread_id: 7,
            target_thread_id: 7,
            source_label: 'Animal Man',
            target_label: 'Swamp Thing',
            note: null,
            explanation: 'Blocked by Animal Man',
          },
        ],
      },
    }

    renderPillar(context)

    await waitFor(() =>
      expect(screen.getByText('Dependency & Continuity Edges')).toBeInTheDocument(),
    )
    expect(screen.getByText('Blocked by Animal Man')).toBeVisible()
  })

  it('suppresses empty panels when no edges exist', async () => {
    renderPillar(baseContext)

    expect(screen.queryByText('Dependency & Continuity Edges')).not.toBeInTheDocument()
  })
})
