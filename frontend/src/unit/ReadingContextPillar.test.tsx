import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { ReadingContextPillar } from '../pages/RollPage/components/ReadingContextPillar'
import { readerContextApi } from '../services/api-reader-context'

vi.mock('../components/Tooltip', () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))
vi.mock('../pages/RollPage/components/ContinuityReadinessSummary', () => ({
  ContinuityReadinessSummary: () => <div data-testid="continuity-readiness" />,
}))
vi.mock('../pages/RollPage/components/ReadingOrderGroups', () => ({
  ReadingOrderGroups: () => <div data-testid="reading-order-groups" />,
}))
vi.mock('../pages/RollPage/components/ReadingRouteExplanation', () => ({
  ReadingRouteExplanation: () => <div data-testid="reading-route-explanation" />,
}))

vi.mock('../services/api-reader-context', () => ({
  readerContextApi: {
    getForIssue: vi.fn(),
  },
}))

const mockedReaderContextApi = vi.mocked(readerContextApi)

const defaultProps = {
  activeRatingThread: {
    id: 1,
    title: 'Test Series',
    format: 'Comic',
    issues_remaining: 5,
    total_issues: 10,
    issue_number: '5',
    next_issue_number: '6',
    issue_id: 100,
    next_issue_id: 101,
  },
  issueId: 101,
  readingOrders: [],
  connectedThreads: [],
  currentDie: 6,
  rolledResult: 3,
  hasValidRolledResult: true,
  poolSize: 6,
}

function createMockReaderContext(overrides: Partial<{
  series: any
  crossovers: any[]
  local_chain: { issues: any[]; edges: any[] }
}> = {}) {
  return {
    issue_id: 101,
    series: {
      identity_source: 'comicvine' as const,
      canonical_series_id: '12345',
      series_name: 'Test Series',
      average_rating: 3.5,
      ratings_count: 8,
      previous_issue: null,
      recent_ratings: [],
      highest_rating: 4.5,
      lowest_rating: 2.5,
      ...overrides.series,
    },
    crossovers: overrides.crossovers ?? [],
    local_chain: {
      issues: overrides.local_chain?.issues ?? [
        {
          issue_id: 99,
          issue_number: '4',
          position: 4,
          status: 'read',
          relation: 'previous',
          rating: 3.0,
          crossover_memberships: [],
        },
        {
          issue_id: 100,
          issue_number: '5',
          position: 5,
          status: 'read',
          relation: 'current',
          rating: 3.5,
          crossover_memberships: [],
        },
        {
          issue_id: 101,
          issue_number: '6',
          position: 6,
          status: 'unread',
          relation: 'next',
          rating: null,
          crossover_memberships: [],
        },
        {
          issue_id: 102,
          issue_number: '7',
          position: 7,
          status: 'unread',
          relation: 'future',
          rating: null,
          crossover_memberships: [],
        },
      ],
      edges: overrides.local_chain?.edges ?? [],
    },
  }
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('ReadingContextPillar', () => {
  it('shows loading state while fetching', () => {
    mockedReaderContextApi.getForIssue.mockImplementation(() => new Promise(() => {}))

    render(<ReadingContextPillar {...defaultProps} />)

    expect(screen.getByRole('heading', { name: '02 READING CONTEXT' })).toBeInTheDocument()
    expect(screen.getByText('Loading reading context…')).toBeInTheDocument()
  })

  it('shows error state with retry button when fetch fails', async () => {
    mockedReaderContextApi.getForIssue.mockRejectedValue(new Error('Network error'))

    render(<ReadingContextPillar {...defaultProps} />)

    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument()
    })
    expect(screen.getByText('Failed to load reading context')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
  })

  it('renders roll result when hasValidRolledResult is true', async () => {
    mockedReaderContextApi.getForIssue.mockResolvedValue(createMockReaderContext())

    render(<ReadingContextPillar {...defaultProps} />)

    await waitFor(() => {
      expect(screen.getByText('Roll Result')).toBeInTheDocument()
    })
    expect(screen.getByText('Rolled 3 on d6')).toBeInTheDocument()
  })

  it('does not render roll result when hasValidRolledResult is false', async () => {
    mockedReaderContextApi.getForIssue.mockResolvedValue(createMockReaderContext())

    render(<ReadingContextPillar { ...defaultProps, hasValidRolledResult: false } />)

    await waitFor(() => {
      expect(screen.queryByText('Roll Result')).not.toBeInTheDocument()
    })
  })

  it('shows eligible count when currentDie > poolSize', async () => {
    mockedReaderContextApi.getForIssue.mockResolvedValue(createMockReaderContext())

    render(<ReadingContextPillar { ...defaultProps, currentDie: 10, poolSize: 6 } />)

    await waitFor(() => {
      expect(screen.getByText('Rolled 3 on d10 · 6 eligible')).toBeInTheDocument()
    })
  })

  it('renders issue identity and position', async () => {
    mockedReaderContextApi.getForIssue.mockResolvedValue(createMockReaderContext())

    render(<ReadingContextPillar {...defaultProps} />)

    await waitFor(() => {
      expect(screen.getByText('Test Series')).toBeInTheDocument()
      expect(screen.getByText('#6')).toBeInTheDocument()
    })
    expect(screen.getByText('Issue 6 of 8 · Position 6')).toBeInTheDocument()
    expect(screen.getByText('50% complete · 5 left')).toBeInTheDocument()
  })

  it('renders series analytics when identity_source is comicvine', async () => {
    mockedReaderContextApi.getForIssue.mockResolvedValue(createMockReaderContext())

    render(<ReadingContextPillar {...defaultProps} />)

    await waitFor(() => {
      expect(screen.getByText('Series Progress')).toBeInTheDocument()
      expect(screen.getByText('3.50')).toBeInTheDocument()
      expect(screen.getByText('Avg Rating')).toBeInTheDocument()
      expect(screen.getByText('8')).toBeInTheDocument()
      expect(screen.getByText('Rated Issues')).toBeInTheDocument()
      expect(screen.getByText('4.5')).toBeInTheDocument()
      expect(screen.getByText('Highest')).toBeInTheDocument()
      expect(screen.getByText('2.5')).toBeInTheDocument()
      expect(screen.getByText('Lowest')).toBeInTheDocument()
    })
  })

  it('does not render series analytics when identity_source is unavailable', async () => {
    mockedReaderContextApi.getForIssue.mockResolvedValue(
      createMockReaderContext({
        series: { identity_source: 'unavailable' as const },
      })
    )

    render(<ReadingContextPillar {...defaultProps} />)

    await waitFor(() => {
      expect(screen.queryByText('Series Progress')).not.toBeInTheDocument()
    })
  })

  describe('Crossover Context', () => {
    it('renders crossover badge for current issue', async () => {
      mockedReaderContextApi.getForIssue.mockResolvedValue(
        createMockReaderContext({
          crossovers: [
            {
              id: 1,
              name: 'Annihilation',
              applies_to_current_issue: true,
              next_member: null,
              average_rating: 3.8,
              ratings_count: 5,
              read_count: 2,
            },
          ],
        })
      )

      render(<ReadingContextPillar {...defaultProps} />)

      await waitFor(() => {
        expect(screen.getByText('Crossover Context')).toBeInTheDocument()
        expect(screen.getByText('Annihilation')).toBeInTheDocument()
        expect(screen.getByText('⟶ CURRENT')).toBeInTheDocument()
        expect(screen.getByText('(2/5)')).toBeInTheDocument()
      })
    })

    it('renders crossover badge for future issue with next member', async () => {
      mockedReaderContextApi.getForIssue.mockResolvedValue(
        createMockReaderContext({
          crossovers: [
            {
              id: 1,
              name: 'Annihilation',
              applies_to_current_issue: false,
              next_member: {
                issue_id: 105,
                issue_number: '12',
                position: 12,
                status: 'unread',
                relation: 'future',
                rating: null,
                crossover_memberships: [],
              },
              average_rating: 3.8,
              ratings_count: 5,
              read_count: 2,
            },
          ],
        })
      )

      render(<ReadingContextPillar {...defaultProps} />)

      await waitFor(() => {
        expect(screen.getByText('Annihilation')).toBeInTheDocument()
        expect(screen.getByText('→ #12')).toBeInTheDocument()
      })
    })

    it('renders multiple crossovers', async () => {
      mockedReaderContextApi.getForIssue.mockResolvedValue(
        createMockReaderContext({
          crossovers: [
            {
              id: 1,
              name: 'Annihilation',
              applies_to_current_issue: true,
              next_member: null,
              average_rating: 3.8,
              ratings_count: 5,
              read_count: 2,
            },
            {
              id: 2,
              name: 'Secret Wars',
              applies_to_current_issue: false,
              next_member: {
                issue_id: 105,
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
          ],
        })
      )

      render(<ReadingContextPillar {...defaultProps} />)

      await waitFor(() => {
        expect(screen.getByText('Annihilation')).toBeInTheDocument()
        expect(screen.getByText('Secret Wars')).toBeInTheDocument()
      })
    })

    it('does not render crossover section when no crossovers', async () => {
      mockedReaderContextApi.getForIssue.mockResolvedValue(
        createMockReaderContext({ crossovers: [] })
      )

      render(<ReadingContextPillar {...defaultProps} />)

      await waitFor(() => {
        expect(screen.queryByText('Crossover Context')).not.toBeInTheDocument()
      })
    })
  })

  describe('Local Reading Chain', () => {
    it('renders local chain with current issue highlighted', async () => {
      mockedReaderContextApi.getForIssue.mockResolvedValue(createMockReaderContext())

      render(<ReadingContextPillar {...defaultProps} />)

      await waitFor(() => {
        expect(screen.getByText('Local Reading Chain')).toBeInTheDocument()
        expect(screen.getByText('YOU ARE HERE')).toBeInTheDocument()
        expect(screen.getByText('#4')).toBeInTheDocument()
        expect(screen.getByText('#5')).toBeInTheDocument()
        expect(screen.getByText('#6')).toBeInTheDocument()
        expect(screen.getByText('#7')).toBeInTheDocument()
      })
    })

    it('shows crossover membership badges on individual chain issues', async () => {
      mockedReaderContextApi.getForIssue.mockResolvedValue(
        createMockReaderContext({
          local_chain: {
            issues: [
              {
                issue_id: 99,
                issue_number: '4',
                position: 4,
                status: 'read',
                relation: 'previous',
                rating: 3.0,
                crossover_memberships: [
                  {
                    issue_id: 99,
                    issue_number: '4',
                    rating: 3.0,
                    status: 'read',
                  },
                ],
              },
              {
                issue_id: 100,
                issue_number: '5',
                position: 5,
                status: 'read',
                relation: 'current',
                rating: 3.5,
                crossover_memberships: [],
              },
              {
                issue_id: 101,
                issue_number: '6',
                position: 6,
                status: 'unread',
                relation: 'next',
                rating: null,
                crossover_memberships: [
                  {
                    issue_id: 101,
                    issue_number: '6',
                    rating: null,
                    status: 'unread',
                  },
                ],
              },
            ],
            edges: [],
          },
        })
      )

      render(<ReadingContextPillar {...defaultProps} />)

      await waitFor(() => {
        expect(screen.getByText('YOU ARE HERE')).toBeInTheDocument()
        expect(screen.getByText('#4')).toBeInTheDocument()
        expect(screen.getByText('4')).toBeInTheDocument()
      })
    })

    it('shows "No local chain data available" when empty', async () => {
      mockedReaderContextApi.getForIssue.mockResolvedValue(
        createMockReaderContext({ local_chain: { issues: [], edges: [] } })
      )

      render(<ReadingContextPillar {...defaultProps} />)

      await waitFor(() => {
        expect(screen.getByText('No local chain data available')).toBeInTheDocument()
      })
    })
  })

  describe('Hard Dependencies (One-Hop)', () => {
    it('renders hard dependency edges', async () => {
      mockedReaderContextApi.getForIssue.mockResolvedValue(
        createMockReaderContext({
          local_chain: {
            issues: [],
            edges: [
              {
                dependency_id: 42,
                source_issue_id: 101,
                target_issue_id: 201,
                source_issue_number: '6',
                target_issue_number: '1',
                source_thread_id: 1,
                target_thread_id: 2,
                source_thread_title: 'Test Series',
                target_thread_title: 'Drax',
                note: 'Must read Drax first',
              },
            ],
          },
        })
      )

      render(<ReadingContextPillar {...defaultProps} />)

      await waitFor(() => {
        expect(screen.getByText('Hard Dependencies (One-Hop)')).toBeInTheDocument()
        expect(screen.getByText('Test Series #6')).toBeInTheDocument()
        expect(screen.getByText('Drax #1')).toBeInTheDocument()
        expect(screen.getByText('Must read Drax first')).toBeInTheDocument()
        expect(screen.getByText('Hard dependency · Edge #42')).toBeInTheDocument()
      })
    })

    it('renders multiple hard dependency edges', async () => {
      mockedReaderContextApi.getForIssue.mockResolvedValue(
        createMockReaderContext({
          local_chain: {
            issues: [],
            edges: [
              {
                dependency_id: 42,
                source_issue_id: 101,
                target_issue_id: 201,
                source_issue_number: '6',
                target_issue_number: '1',
                source_thread_id: 1,
                target_thread_id: 2,
                source_thread_title: 'Test Series',
                target_thread_title: 'Drax',
                note: 'Must read Drax first',
              },
              {
                dependency_id: 43,
                source_issue_id: 301,
                target_issue_id: 101,
                source_issue_number: '5',
                target_issue_number: '6',
                source_thread_id: 3,
                target_thread_id: 1,
                source_thread_title: 'Nova',
                target_thread_title: 'Test Series',
                note: null,
              },
            ],
          },
        })
      )

      render(<ReadingContextPillar {...defaultProps} />)

      await waitFor(() => {
        expect(screen.getByText('Test Series #6')).toBeInTheDocument()
        expect(screen.getByText('Drax #1')).toBeInTheDocument()
        expect(screen.getByText('Nova #5')).toBeInTheDocument()
        expect(screen.getByText('Test Series #6')).toBeInTheDocument()
      })
    })

    it('does not render hard dependencies section when no edges', async () => {
      mockedReaderContextApi.getForIssue.mockResolvedValue(
        createMockReaderContext({ local_chain: { issues: [], edges: [] } })
      )

      render(<ReadingContextPillar {...defaultProps} />)

      await waitFor(() => {
        expect(screen.queryByText('Hard Dependencies (One-Hop)')).not.toBeInTheDocument()
      })
    })
  })

  describe('Reading Routes', () => {
    it('renders reading routes when available', async () => {
      mockedReaderContextApi.getForIssue.mockResolvedValue(createMockReaderContext())

      render(
        <ReadingContextPillar
          {...defaultProps}
          readingOrders={[
            { id: 1, name: 'Cosmic Saga', total_items: 10, completed_items: 5 },
            { id: 2, name: 'Event Timeline', total_items: 20, completed_items: 8 },
          ]}
        />
      )

      await waitFor(() => {
        expect(screen.getByText('Reading Routes')).toBeInTheDocument()
        expect(screen.getByText('Cosmic Saga')).toBeInTheDocument()
        expect(screen.getByText('5 of 10 complete · 50%')).toBeInTheDocument()
        expect(screen.getByText('Event Timeline')).toBeInTheDocument()
        expect(screen.getByText('8 of 20 complete · 40%')).toBeInTheDocument()
      })
    })

    it('does not render reading routes section when empty', async () => {
      mockedReaderContextApi.getForIssue.mockResolvedValue(createMockReaderContext())

      render(<ReadingContextPillar {...defaultProps} readingOrders={[]} />)

      await waitFor(() => {
        expect(screen.queryByText('Reading Routes')).not.toBeInTheDocument()
      })
    })
  })

  describe('Explain Route button', () => {
    it('renders Explain Route button in header', async () => {
      mockedReaderContextApi.getForIssue.mockResolvedValue(createMockReaderContext())

      render(<ReadingContextPillar {...defaultProps} />)

      await waitFor(() => {
        expect(screen.getByRole('button', { name: 'Explain Route' })).toBeInTheDocument()
      })
    })

    it('renders View Full Dependency Graph button at bottom', async () => {
      mockedReaderContextApi.getForIssue.mockResolvedValue(createMockReaderContext())

      render(<ReadingContextPillar {...defaultProps} />)

      await waitFor(() => {
        expect(screen.getByRole('button', { name: 'View Full Dependency Graph' })).toBeInTheDocument()
      })
    })
  })

  describe('Retry functionality', () => {
    it('retries fetch when retry button is clicked', async () => {
      mockedReaderContextApi.getForIssue
        .mockRejectedValueOnce(new Error('Network error'))
        .mockResolvedValueOnce(createMockReaderContext())

      render(<ReadingContextPillar {...defaultProps} />)

      await waitFor(() => {
        expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
      })

      await userEvent.click(screen.getByRole('button', { name: 'Retry' }))

      await waitFor(() => {
        expect(mockedReaderContextApi.getForIssue).toHaveBeenCalledTimes(2)
        expect(screen.getByText('Roll Result')).toBeInTheDocument()
      })
    })
  })
})