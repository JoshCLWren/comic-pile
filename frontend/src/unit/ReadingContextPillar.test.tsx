import { render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { ReadingContextPillar } from '../pages/RollPage/components/ReadingContextPillar'
import type { ReaderContextResponse } from '../services/api-reader-context'
import type { RatingThread } from '../pages/RollPage/types'
import type { ConnectedThreadInfo } from '../types'

vi.mock('../components/Tooltip', () => ({
  default: ({ children, content }: { children: React.ReactNode; content: string }) => (
    <span title={content}>{children}</span>
  ),
}))

vi.mock('../pages/RollPage/components/ContinuityReadinessSummary', () => ({
  ContinuityReadinessSummary: () => <div data-testid="readiness-summary" />,
}))

vi.mock('../pages/RollPage/components/ReadingOrderGroups', () => ({
  ReadingOrderGroups: () => <div data-testid="reading-order-groups" />,
}))

vi.mock('../pages/RollPage/components/ReadingRouteExplanation', () => ({
  ReadingRouteExplanation: () => null,
}))

const mockGet = vi.fn()
vi.mock('../services/api', () => ({
  default: {
    get: (...args: unknown[]) => mockGet(...args),
  },
}))

const thread: RatingThread = {
  id: 1,
  title: 'Thanos',
  format: 'Comic',
  issues_remaining: 3,
  total_issues: 10,
  issue_number: '10',
  next_issue_number: '10',
} as never

const connectedThreads: ConnectedThreadInfo[] = [
  {
    thread_id: 2,
    title: 'Drax',
    connection_type: 'blocks',
    dependency_id: 1,
  },
]

function createMockResponse(overrides: Partial<ReaderContextResponse> = {}): ReaderContextResponse {
  return {
    issue_id: 100,
    series: {
      identity_source: 'comicvine',
      canonical_series_id: '20764',
      series_name: 'Thanos',
      average_rating: 3.71,
      ratings_count: 7,
      previous_issue: {
        issue_id: 99,
        issue_number: '9',
        position: 9,
        status: 'read',
        relation: 'previous',
        rating: 3.5,
        crossover_memberships: [],
      },
      recent_ratings: [],
      highest_rating: 4.5,
      lowest_rating: 3.0,
    },
    crossovers: [],
    local_chain: {
      issues: [
        {
          issue_id: 98,
          issue_number: '8',
          position: 8,
          status: 'read',
          relation: 'previous',
          rating: 4.0,
          crossover_memberships: [],
        },
        {
          issue_id: 99,
          issue_number: '9',
          position: 9,
          status: 'read',
          relation: 'previous',
          rating: 3.5,
          crossover_memberships: [],
        },
        {
          issue_id: 100,
          issue_number: '10',
          position: 10,
          status: 'unread',
          relation: 'current',
          rating: null,
          crossover_memberships: [],
        },
        {
          issue_id: 101,
          issue_number: '11',
          position: 11,
          status: 'unread',
          relation: 'next',
          rating: null,
          crossover_memberships: [],
        },
        {
          issue_id: 102,
          issue_number: '12',
          position: 12,
          status: 'unread',
          relation: 'future',
          rating: null,
          crossover_memberships: [],
        },
      ],
      edges: [],
    },
    ...overrides,
  }
}

function renderPillar(overrides: Partial<React.ComponentProps<typeof ReadingContextPillar>> = {}) {
  mockGet.mockResolvedValue(createMockResponse())

  return render(
    <ReadingContextPillar
      activeRatingThread={thread}
      issueId={100}
      readingOrders={[]}
      connectedThreads={connectedThreads}
      {...overrides}
    />,
  )
}

describe('ReadingContextPillar', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders loading state initially', () => {
    renderPillar()
    expect(screen.getByText('Loading reading context…')).toBeInTheDocument()
  })

  it('renders the local chain after loading', async () => {
    renderPillar()
    await waitFor(() => {
      expect(screen.getAllByText('#10').length).toBeGreaterThan(0)
    })
    expect(screen.getByText('YOU ARE HERE')).toBeInTheDocument()
  })

  it('renders series analytics when identity source is comicvine', async () => {
    renderPillar()
    await waitFor(() => {
      expect(screen.getByText('Series Analytics')).toBeInTheDocument()
    })
    expect(screen.getByText('3.71')).toBeInTheDocument()
    expect(screen.getByText('Thanos')).toBeInTheDocument()
  })

  it('does not render series analytics when identity is unavailable', async () => {
    mockGet.mockResolvedValue(
      createMockResponse({
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
      }),
    )

    render(
      <ReadingContextPillar
        activeRatingThread={thread}
        issueId={100}
        readingOrders={[]}
        connectedThreads={connectedThreads}
      />,
    )

    await waitFor(() => {
      expect(screen.queryByText('Series Analytics')).not.toBeInTheDocument()
    })
  })

  it('renders empty local chain state', async () => {
    mockGet.mockResolvedValue(
      createMockResponse({
        local_chain: { issues: [], edges: [] },
      }),
    )

    render(
      <ReadingContextPillar
        activeRatingThread={thread}
        issueId={100}
        readingOrders={[]}
        connectedThreads={connectedThreads}
      />,
    )

    await waitFor(() => {
      expect(screen.getByText('No local chain data available')).toBeInTheDocument()
    })
  })

  it('renders hard dependency edges', async () => {
    mockGet.mockResolvedValue(
      createMockResponse({
        local_chain: {
          issues: [
            {
              issue_id: 100,
              issue_number: '10',
              position: 10,
              status: 'unread',
              relation: 'current',
              rating: null,
              crossover_memberships: [],
            },
          ],
          edges: [
            {
              dependency_id: 1,
              source_issue_id: 100,
              target_issue_id: 200,
              source_issue_number: '10',
              target_issue_number: '1',
              source_thread_id: 1,
              target_thread_id: 2,
              source_thread_title: 'Thanos',
              target_thread_title: 'Drax',
              note: 'Must read before Drax',
            },
          ],
        },
      }),
    )

    render(
      <ReadingContextPillar
        activeRatingThread={thread}
        issueId={100}
        readingOrders={[]}
        connectedThreads={connectedThreads}
      />,
    )

    await waitFor(() => {
      expect(screen.getByText('Hard Dependencies (One-Hop)')).toBeInTheDocument()
    })
    expect(screen.getByText('Thanos #10')).toBeInTheDocument()
    expect(screen.getByText('Drax #1')).toBeInTheDocument()
    expect(screen.getByText('Must read before Drax')).toBeInTheDocument()
  })

  it('renders multiple crossovers with correct badges', async () => {
    mockGet.mockResolvedValue(
      createMockResponse({
        crossovers: [
          {
            id: 1,
            name: 'Annihilation',
            applies_to_current_issue: false,
            next_member: {
              issue_id: 102,
              issue_number: '12',
              position: 12,
              status: 'unread',
              relation: 'future',
              rating: null,
              crossover_memberships: [],
            },
            average_rating: 4.0,
            ratings_count: 3,
            read_count: 1,
          },
          {
            id: 2,
            name: 'Infinity Gauntlet',
            applies_to_current_issue: true,
            next_member: null,
            average_rating: 3.5,
            ratings_count: 2,
            read_count: 2,
          },
        ],
      }),
    )

    render(
      <ReadingContextPillar
        activeRatingThread={thread}
        issueId={100}
        readingOrders={[]}
        connectedThreads={connectedThreads}
      />,
    )

    await waitFor(() => {
      expect(screen.getByText('Annihilation')).toBeInTheDocument()
    })
    expect(screen.getByText('Infinity Gauntlet')).toBeInTheDocument()
    expect(screen.getByText('→ #12')).toBeInTheDocument()
    expect(screen.getByText('⟶ MEMBER')).toBeInTheDocument()
  })

  it('renders error state and retry button', async () => {
    mockGet.mockRejectedValue(new Error('Network error'))

    render(
      <ReadingContextPillar
        activeRatingThread={thread}
        issueId={100}
        readingOrders={[]}
        connectedThreads={connectedThreads}
      />,
    )

    await waitFor(() => {
      expect(screen.getByText('Failed to load reading context')).toBeInTheDocument()
    })
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument()
  })

  it('does not fetch when issueId is null', () => {
    render(
      <ReadingContextPillar
        activeRatingThread={thread}
        issueId={null}
        readingOrders={[]}
        connectedThreads={connectedThreads}
      />,
    )

    expect(mockGet).not.toHaveBeenCalled()
  })

  it('renders reading orders', async () => {
    mockGet.mockResolvedValue(createMockResponse())

    render(
      <ReadingContextPillar
        activeRatingThread={thread}
        issueId={100}
        readingOrders={[
          {
            id: 1,
            name: 'Marvel Reading Order',
            total_items: 100,
            completed_items: 25,
          } as never,
        ]}
        connectedThreads={connectedThreads}
      />,
    )

    await waitFor(() => {
      expect(screen.getByText('Reading Routes')).toBeInTheDocument()
    })
    expect(screen.getByText('Marvel Reading Order')).toBeInTheDocument()
    expect(screen.getByText('25 of 100 complete · 25%')).toBeInTheDocument()
  })

  it('renders crossover memberships on chain nodes', async () => {
    mockGet.mockResolvedValue(
      createMockResponse({
        local_chain: {
          issues: [
            {
              issue_id: 100,
              issue_number: '10',
              position: 10,
              status: 'unread',
              relation: 'current',
              rating: null,
              crossover_memberships: [
                {
                  issue_id: 100,
                  issue_number: '10',
                  rating: null,
                  status: 'unread',
                },
              ],
            },
          ],
          edges: [],
        },
      }),
    )

    render(
      <ReadingContextPillar
        activeRatingThread={thread}
        issueId={100}
        readingOrders={[]}
        connectedThreads={connectedThreads}
      />,
    )

    await waitFor(() => {
      expect(screen.getAllByText('#10').length).toBeGreaterThan(0)
    })
    expect(screen.getAllByText('10').length).toBeGreaterThan(0)
  })
})
