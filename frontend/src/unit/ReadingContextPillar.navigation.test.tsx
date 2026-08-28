import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ReadingContextPillar } from '../pages/RollPage/components/ReadingContextPillar'
import type { ReaderContextResponse } from '../types'

const navigateSpy = vi.fn()

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return { ...actual, useNavigate: () => navigateSpy }
})

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
vi.mock('../hooks/useContinuityReadiness', () => ({
  useContinuityReadiness: () => ({ readiness: null, isLoading: false, error: null, refetch: vi.fn() }),
}))
vi.mock('../pages/RollPage/components/ReadingPathPanel', () => ({
  ReadingPathPanel: () => null,
}))

beforeEach(() => {
  navigateSpy.mockClear()
})

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
    crossovers: [],
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
          explanation: 'Blocked by issue #3 in Saga',
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

function renderPillar(context: ReaderContextResponse) {
  return render(
    <ReadingContextPillar
      activeRatingThread={activeRatingThread}
      readingOrders={[]}
      connectedThreads={[]}
      onRefreshThread={vi.fn()}
      rolledResult={null}
      currentDie={10}
      readerContext={context}
      isReaderContextLoading={false}
      readerContextError={null}
    />,
  )
}

describe('ReadingContextPillar navigation (issue #1877)', () => {
  it('opens the selected chain node\'s own context instead of navigating to the active thread', async () => {
    renderPillar(buildContext())

    const previousNode = await screen.findByRole('button', { name: 'Show context for Ultimate Black Panther issue 3' })
    await userEvent.setup().click(previousNode)

    expect(previousNode).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText('Issue 3 · Already read · Your rating: ★★★½')).toBeVisible()
    expect(navigateSpy).not.toHaveBeenCalled()
  })

  it('produces different contexts when different chain nodes are selected', async () => {
    renderPillar(buildContext())

    const previousNode = await screen.findByRole('button', { name: 'Show context for Ultimate Black Panther issue 3' })
    const currentNode = screen.getByRole('button', { name: 'Show context for Ultimate Black Panther issue 5' })

    await userEvent.setup().click(previousNode)
    const previousPanel = screen.getByLabelText('Context for Ultimate Black Panther issue 3')
    expect(within(previousPanel).getByText('Earlier in Ultimate Black Panther')).toBeVisible()

    await userEvent.setup().click(currentNode)
    expect(screen.queryByLabelText('Context for Ultimate Black Panther issue 3')).not.toBeInTheDocument()
    const currentPanel = screen.getByLabelText('Context for Ultimate Black Panther issue 5')
    expect(within(currentPanel).getByText('Issue 5 · Not read yet')).toBeVisible()
    expect(within(currentPanel).getByRole('button', { name: 'Open Saga thread' })).toBeVisible()
  })

  it('exposes the active-thread surface from the current node\'s own context', async () => {
    renderPillar(buildContext())

    const currentNode = await screen.findByRole('button', { name: 'Show context for Ultimate Black Panther issue 5' })
    await userEvent.setup().click(currentNode)

    await userEvent.setup().click(screen.getByRole('button', { name: 'Open Saga thread' }))
    expect(navigateSpy).toHaveBeenCalledTimes(1)
    expect(navigateSpy).toHaveBeenCalledWith('/thread/42')
  })

  it('activates chain nodes consistently by pointer, Enter, and Space', async () => {
    const user = userEvent.setup()
    renderPillar(buildContext())

    const node = await screen.findByRole('button', { name: 'Show context for Ultimate Black Panther issue 3' })
    await user.click(node)
    expect(node).toHaveAttribute('aria-expanded', 'true')

    await user.keyboard('{Enter}')
    expect(node).toHaveAttribute('aria-expanded', 'false')

    await user.keyboard(' ')
    expect(node).toHaveAttribute('aria-expanded', 'true')
    expect(navigateSpy).not.toHaveBeenCalled()
  })

  it('links edge endpoint buttons deep to their threads', async () => {
    renderPillar(
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
          edges: [
            {
              id: 21,
              kind: 'dependency' as const,
              source_issue_id: 98,
              target_issue_id: 100,
              source_thread_id: 42,
              target_thread_id: 7,
              source_label: 'Saga #3',
              target_label: 'Saga #5',
              note: null,
              explanation: 'Read first',
            },
          ],
        },
      }),
    )

    await screen.findByText('Dependency & Continuity Edges')
    await userEvent.setup().click(screen.getByRole('button', { name: 'Open thread for Saga #3' }))
    expect(navigateSpy).toHaveBeenCalledWith('/thread/42')

    await userEvent.setup().click(screen.getByRole('button', { name: 'Open thread for Saga #5' }))
    expect(navigateSpy).toHaveBeenCalledWith('/thread/7')
  })

  it('links both dependency edge endpoints to their threads and shows the explanation', async () => {
    renderPillar(buildContext())

    const sources = await screen.findAllByRole('button', { name: 'Open thread for Saga #3' })
    expect(sources).toHaveLength(2)
    const targets = screen.getAllByRole('button', { name: 'Open thread for Saga #5' })
    expect(targets).toHaveLength(2)
    await userEvent.setup().click(sources[0])
    expect(navigateSpy).toHaveBeenLastCalledWith('/thread/42')

    await userEvent.setup().click(targets[1])
    expect(navigateSpy).toHaveBeenLastCalledWith('/thread/42')
    expect(screen.getAllByText('Blocked by issue #3 in Saga')).toHaveLength(1)
    expect(screen.getByText('Saga #3 must be read before Saga #5')).toBeVisible()
  })

  it('links the membership chips above the series strip to their specific crossovers', async () => {
    renderPillar(
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

    const chip = await screen.findByRole('button', { name: 'Open Animal Man crossover' })
    await userEvent.setup().click(chip)
    expect(navigateSpy).toHaveBeenLastCalledWith('/crossovers?group=9')
  })

  it('labels incoming dependency edges "Blocked by:" without counts', async () => {
    renderPillar(buildContext())

    expect(await screen.findByText('Blocked by:')).toBeVisible()
    expect(screen.queryByText(/1 edges/)).not.toBeInTheDocument()
  })

  it('labels outgoing dependency edges "Blocks:"', async () => {
    renderPillar(
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
              explanation: 'Blocked by issue #5 in Saga',
            },
          ],
        },
      }),
    )

    expect(await screen.findByText('Blocks:')).toBeVisible()
  })

  it('suppresses empty panels and falls back to note copy when no explanation exists', async () => {
    renderPillar(
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

    await screen.findByText('Continuity:')
    expect(screen.getByText('#100')).toBeVisible()
    expect(screen.getByText('#101')).toBeVisible()
    expect(screen.getByText('checkpoint')).toBeVisible()
  })
})
