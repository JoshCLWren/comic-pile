import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { ReadingContextPillar } from '../pages/RollPage/components/ReadingContextPillar'
import type { ReaderContextResponse } from '../types'

const navigateSpy = vi.fn()

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return { ...actual, useNavigate: () => navigateSpy }
})

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
vi.mock('../pages/RollPage/components/ReadingRouteExplanation', () => ({
  ReadingRouteExplanation: () => null,
}))
vi.mock('../components/ContinuityCorrectionDialog', () => ({
  default: () => null,
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

  it('labels mixed-direction dependency edges as Dependency edges', async () => {
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
            target_issue_id: 102,
            source_thread_id: 7,
            target_thread_id: 8,
            source_label: 'Source',
            target_label: 'Target',
            note: null,
            explanation: 'A dependency',
          },
        ],
      },
    }

    renderPillar(context)

    await waitFor(() =>
      expect(screen.getByText('Dependency edges:')).toBeInTheDocument(),
    )
  })

  it('renders edge endpoint as a span when threadId is null', async () => {
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
            id: 14,
            kind: 'dependency',
            source_issue_id: 101,
            target_issue_id: 99,
            source_thread_id: null,
            target_thread_id: null,
            source_label: 'Orphan A',
            target_label: 'Orphan B',
            note: null,
            explanation: 'No thread',
          },
        ],
      },
    }

    renderPillar(context)

    await waitFor(() =>
      expect(screen.getByText('Dependency & Continuity Edges')).toBeInTheDocument(),
    )
    expect(screen.getByText('Orphan A')).toBeVisible()
    expect(screen.getByText('Orphan B')).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Open thread for Orphan A' })).not.toBeInTheDocument()
  })

  it('falls back to note when explanation is null on an edge', async () => {
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
            id: 15,
            kind: 'dependency',
            source_issue_id: 101,
            target_issue_id: 99,
            source_thread_id: 7,
            target_thread_id: 8,
            source_label: 'A',
            target_label: 'B',
            note: 'fallback note text',
            explanation: null,
          },
        ],
      },
    }

    renderPillar(context)

    await waitFor(() =>
      expect(screen.getByText('fallback note text')).toBeInTheDocument(),
    )
  })
})

describe('ReadingContextPillar loading and error states', () => {
  it('shows loading skeleton when loading and no context', () => {
    render(
      <MemoryRouter>
        <ReadingContextPillar
          activeRatingThread={ratingThread}
          readingOrders={[]}
          connectedThreads={[]}
          onRefreshThread={vi.fn()}
          rolledResult={null}
          currentDie={6}
          readerContext={null}
          isReaderContextLoading={true}
          readerContextError={null}
        />
      </MemoryRouter>,
    )
    expect(screen.getByText('Reading Context')).toBeInTheDocument()
  })

  it('shows error message when context fails to load', () => {
    render(
      <MemoryRouter>
        <ReadingContextPillar
          activeRatingThread={ratingThread}
          readingOrders={[]}
          connectedThreads={[]}
          onRefreshThread={vi.fn()}
          rolledResult={null}
          currentDie={6}
          readerContext={null}
          isReaderContextLoading={false}
          readerContextError="Network timeout"
        />
      </MemoryRouter>,
    )
    expect(screen.getByText('Local reading context unavailable')).toBeInTheDocument()
    expect(screen.getByText('Network timeout')).toBeInTheDocument()
  })
})

describe('ReadingContextPillar relation label variants', () => {
  it('renders future relation label with series name', async () => {
    const context: ReaderContextResponse = {
      ...baseContext,
      series: {
        ...baseContext.series,
        series_name: 'Amazing Spider-Man',
      },
      local_chain: {
        issues: [
          {
            issue_id: 200,
            issue_number: '10',
            position: 5,
            status: 'unread',
            relation: 'future',
            rating: null,
            crossover_memberships: [],
          },
        ],
        edges: [],
      },
    }

    renderPillar(context)

    const button = await screen.findByRole('button', { name: /Show context for Amazing Spider-Man issue 10/ })
    await userEvent.setup().click(button)

    expect(screen.getByText('Later in Amazing Spider-Man')).toBeVisible()
  })

  it('renders next relation label', async () => {
    const context: ReaderContextResponse = {
      ...baseContext,
      series: {
        ...baseContext.series,
        series_name: 'Saga',
      },
      local_chain: {
        issues: [
          {
            issue_id: 200,
            issue_number: '10',
            position: 5,
            status: 'unread',
            relation: 'next',
            rating: null,
            crossover_memberships: [],
          },
        ],
        edges: [],
      },
    }

    renderPillar(context)

    const button = await screen.findByRole('button', { name: /Show context for Saga issue 10/ })
    await userEvent.setup().click(button)

    expect(screen.getByText('Next up')).toBeVisible()
  })
})

describe('ReadingContextPillar crossover membership chips', () => {
  it('renders crossover membership chips and navigates on click', async () => {
    const context: ReaderContextResponse = {
      ...baseContext,
      series: {
        ...baseContext.series,
        series_name: 'Animal Man',
      },
      local_chain: {
        issues: [
          {
            issue_id: 101,
            issue_number: '2',
            position: 2,
            status: 'read',
            relation: 'previous',
            rating: 4.0,
            crossover_memberships: [{ id: 3, name: 'Annihilation' }],
          },
        ],
        edges: [],
      },
    }

    renderPillar(context)

    const button = await screen.findByRole('button', { name: /Show context for Animal Man issue 2/ })
    await userEvent.setup().click(button)

    const chip = screen.getByRole('button', { name: 'Open Annihilation crossover' })
    expect(chip).toBeVisible()
    await userEvent.setup().click(chip)
    expect(navigateSpy).toHaveBeenCalledWith('/crossovers?group=3')
  })
})
