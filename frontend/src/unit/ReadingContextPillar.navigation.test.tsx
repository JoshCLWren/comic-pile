import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ReadingContextPillar } from '../pages/RollPage/components/ReadingContextPillar'
import { issuesApi } from '../services/api-issues'
import type { ReaderContextResponse } from '../types'

const navigateSpy = vi.fn()

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return { ...actual, useNavigate: () => navigateSpy }
})

vi.mock('../services/api-issues', () => ({
  issuesApi: {
    getReaderContext: vi.fn(),
  },
}))

vi.mock('../components/ContinuityCorrectionDialog', () => ({ default: () => null }))
vi.mock('../pages/RollPage/components/ContinuityReadinessSummary', () => ({
  ContinuityReadinessSummary: () => null,
}))
vi.mock('../pages/RollPage/components/ReadingOrderGroups', () => ({
  ReadingOrderGroups: () => null,
}))
vi.mock('../pages/RollPage/components/ReadingRouteExplanation', () => ({
  ReadingRouteExplanation: () => null,
}))

const getReaderContextMock = issuesApi.getReaderContext as ReturnType<typeof vi.fn>

const activeRatingThread = {
  id: 42,
  title: 'Saga',
  format: 'Comic',
  issues_remaining: 5,
  queue_position: 0,
  total_issues: 10,
  reading_progress: 'in_progress',
  issue_id: 100,
  issue_number: '3',
  next_issue_id: 101,
  next_issue_number: '4',
  last_rolled_result: null,
}

function buildContext(overrides: Partial<ReaderContextResponse> = {}): ReaderContextResponse {
  return {
    issue_id: 100,
    series: {
      identity_source: 'comicvine',
      canonical_series_id: '1-111',
      series_name: 'Ultimate Black Panther',
      average_rating: null,
      ratings_count: 0,
      previous_issue: null,
      recent_ratings: [],
      highest_rating: null,
      lowest_rating: null,
    },
    crossovers: [
      {
        id: 7,
        name: 'Ultimate Universe Reading Order',
        applies_to_current_issue: false,
        next_member: { issue_id: 205, issue_number: '14' },
        average_rating: null,
        ratings_count: 0,
        read_count: 0,
      },
    ],
    local_chain: {
      issues: [
        {
          issue_id: 98,
          issue_number: '3',
          position: 2,
          status: 'read',
          relation: 'previous',
          rating: 3.5,
          crossover_memberships: [{ id: 7, name: 'Ultimate Universe Reading Order' }],
        },
        {
          issue_id: 100,
          issue_number: '5',
          position: 4,
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
          target_issue_id: 100,
          source_thread_id: 42,
          target_thread_id: 42,
          source_label: 'Saga #3',
          target_label: 'Saga #5',
          note: null,
          explanation: 'Blocked by issue #3 in Saga (thread #42)',
        },
        {
          id: 12,
          kind: 'continuity',
          source_issue_id: 98,
          target_issue_id: 100,
          source_thread_id: 42,
          target_thread_id: 42,
          source_label: 'Saga #3',
          target_label: 'Saga #5',
          note: null,
          explanation: 'Saga #3 must be read before Saga #5',
        },
      ],
    },
    ...overrides,
  }
}

function renderPillar() {
  return render(
    <ReadingContextPillar
      activeRatingThread={activeRatingThread}
      readingOrders={[]}
      connectedThreads={[]}
      onRefreshThread={vi.fn()}
      rolledResult={null}
      currentDie={10}
    />,
  )
}

describe('ReadingContextPillar navigation (issue #1670)', () => {
  it('navigates to the thread when a series-chain node is clicked or keyed', async () => {
    getReaderContextMock.mockResolvedValue(buildContext())
    renderPillar()

    const node = await screen.findByRole('listitem', { name: /open saga issue 5/i })
    await userEvent.setup().click(node)
    expect(navigateSpy).toHaveBeenCalledWith('/thread/42')

    fireEvent.keyDown(node, { key: 'Enter' })
    expect(navigateSpy).toHaveBeenLastCalledWith('/thread/42')
  })

  it('links each crossover name in the crossover panel to the crossovers page', async () => {
    getReaderContextMock.mockResolvedValue(
      buildContext({
        local_chain: {
          issues: [
            ...buildContext().local_chain.issues.slice(0, 1),
            {
              issue_id: 100,
              issue_number: '5',
              position: 4,
              status: 'unread',
              relation: 'current',
              rating: null,
              crossover_memberships: [{ id: 9, name: 'Animal Man' }],
            },
          ],
          edges: [],
        },
      }),
    )
    renderPillar()

    await screen.findByText('Exact Crossover Context')
    await userEvent.setup().click(screen.getByRole('button', { name: 'Open crossover Animal Man' }))
    expect(navigateSpy).toHaveBeenLastCalledWith('/crossovers')

    await userEvent.setup().click(screen.getByRole('button', { name: 'Open crossover Ultimate Universe Reading Order' }))
    expect(navigateSpy).toHaveBeenLastCalledWith('/crossovers')
  })

  it('states where an upcoming crossover begins instead of a bare placeholder', async () => {
    getReaderContextMock.mockResolvedValue(buildContext())
    renderPillar()

    expect(await screen.findByText(/starts at #14/)).toBeVisible()
  })

  it('links both dependency edge endpoints to their threads and shows the explanation', async () => {
    getReaderContextMock.mockResolvedValue(buildContext())
    renderPillar()

    const source = await screen.findByRole('button', { name: 'Open thread for Saga #3' })
    expect(screen.getByRole('button', { name: 'Open thread for Saga #5' })).toBeVisible()
    await userEvent.setup().click(source)
    expect(navigateSpy).toHaveBeenLastCalledWith('/thread/42')

    await userEvent.setup().click(screen.getByRole('button', { name: 'Open thread for Saga #5' }))
    expect(navigateSpy).toHaveBeenLastCalledWith('/thread/42')
    expect(screen.getByText('Blocked by issue #3 in Saga (thread #42)')).toBeVisible()
    expect(screen.getByText('Saga #3 must be read before Saga #5')).toBeVisible()
  })

  it('labels incoming dependency edges "Blocked by:" without counts', async () => {
    getReaderContextMock.mockResolvedValue(buildContext())
    renderPillar()

    expect(await screen.findByText('Blocked by:')).toBeVisible()
    expect(screen.queryByText(/1 edges/)).not.toBeInTheDocument()
  })

  it('labels outgoing dependency edges "Blocks:"', async () => {
    getReaderContextMock.mockResolvedValue(
      buildContext({
        local_chain: {
          issues: buildContext().local_chain.issues,
          edges: [
            {
              id: 21,
              kind: 'dependency',
              source_issue_id: 100,
              target_issue_id: 101,
              source_thread_id: 42,
              target_thread_id: 43,
              source_label: 'Saga #5',
              target_label: 'Other #1',
              note: null,
              explanation: 'Blocked by issue #5 in Saga (thread #42)',
            },
          ],
        },
      }),
    )
    renderPillar()

    expect(await screen.findByText('Blocks:')).toBeVisible()
  })

  it('suppresses empty panels and falls back to note copy when no explanation exists', async () => {
    getReaderContextMock.mockResolvedValue(
      buildContext({
        crossovers: [],
        local_chain: {
          issues: [
            {
              issue_id: 100,
              issue_number: '5',
              position: 4,
              status: 'unread',
              relation: 'current',
              rating: null,
              crossover_memberships: [],
            },
          ],
          edges: [
            {
              id: 13,
              kind: 'continuity',
              source_issue_id: 100,
              target_issue_id: 101,
              source_thread_id: null,
              target_thread_id: null,
              source_label: null,
              target_label: null,
              note: 'checkpoint',
              explanation: null,
            },
          ],
        },
      }),
    )
    renderPillar()

    await screen.findByText('Continuity:')
    expect(screen.queryByText(/Current Issue Crossovers/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/Upcoming Crossovers/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/0 upcoming/i)).not.toBeInTheDocument()
    expect(screen.getByText('#100')).toBeVisible()
    expect(screen.getByText('#101')).toBeVisible()
    expect(screen.getByText('checkpoint')).toBeVisible()
  })
})
