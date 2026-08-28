import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { YourContextPillar } from '../pages/RollPage/components/YourContextPillar'

vi.mock('../components/Tooltip', () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

vi.mock('../pages/RollPage/components/SeriesPanel', () => ({
  SeriesPanel: ({ series }: { series: { identity_source: string; series_name?: string; ratings_count?: number } }) => (
    <div data-testid="series-panel">
      {series.identity_source === 'unavailable'
        ? 'Canonical series history unavailable'
        : `Series: ${series.series_name ?? 'Unknown'} (${series.ratings_count ?? 0} rated)`}
    </div>
  ),
}))

vi.mock('../pages/RollPage/components/CrossoverAnalytics', () => ({
  CrossoverAnalytics: ({ crossovers }: { crossovers: { name: string }[] }) => (
    <div data-testid="crossover-analytics">
      {crossovers.length > 0
        ? crossovers.map((c) => <span key={c.name}>{c.name}</span>)
        : null}
    </div>
  ),
}))

function ratingThread(overrides: Record<string, unknown> = {}) {
  return {
    id: 1,
    title: 'Saga',
    format: 'Comic',
    issues_remaining: 5,
    total_issues: 10,
    issue_number: '3',
    next_issue_number: '4',
    reading_progress: 'in_progress',
    queue_position: 0,
    issue_id: 100,
    next_issue_id: 101,
    ...overrides,
  }
}

describe('YourContextPillar reader-context integration', () => {
  it('shows skeleton loading state while fetching', () => {
    const { container } = render(
      <YourContextPillar
        activeRatingThread={ratingThread()}
        currentDie={6}
        rating={3.0}
        predictedDie={8}
        onUpdateRating={vi.fn()}
        readerContext={null}
        isLoading={true}
      />,
    )
    const skeletons = container.querySelectorAll('.animate-pulse')
    expect(skeletons.length).toBeGreaterThan(0)
  })

  it('renders series panel with unavailable data', () => {
    render(
      <YourContextPillar
        activeRatingThread={ratingThread()}
        currentDie={6}
        rating={3.0}
        predictedDie={8}
        onUpdateRating={vi.fn()}
        readerContext={{
          issue_id: 100,
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
          local_chain: { issues: [], edges: [] },
        }}
        isLoading={false}
      />,
    )
    expect(screen.getByTestId('series-panel')).toHaveTextContent(
      'Canonical series history unavailable',
    )
  })

  it('renders series panel with populated data', () => {
    render(
      <YourContextPillar
        activeRatingThread={ratingThread()}
        currentDie={6}
        rating={3.0}
        predictedDie={8}
        onUpdateRating={vi.fn()}
        readerContext={{
          issue_id: 100,
          series: {
            identity_source: 'comicvine',
            canonical_series_id: '20764',
            series_name: 'Thanos',
            average_rating: 3.71,
            ratings_count: 7,
            previous_issue: null,
            recent_ratings: [],
            highest_rating: null,
            lowest_rating: null,
          },
          crossovers: [],
          local_chain: { issues: [], edges: [] },
        }}
        isLoading={false}
      />,
    )
    expect(screen.getByTestId('series-panel')).toHaveTextContent(
      'Series: Thanos (7 rated)',
    )
  })

  it('renders crossover analytics when present', () => {
    render(
      <YourContextPillar
        activeRatingThread={ratingThread()}
        currentDie={6}
        rating={3.0}
        predictedDie={8}
        onUpdateRating={vi.fn()}
        readerContext={{
          issue_id: 100,
          series: {
            identity_source: 'comicvine',
            canonical_series_id: '20764',
            series_name: 'Thanos',
            average_rating: null,
            ratings_count: 0,
            previous_issue: null,
            recent_ratings: [],
            highest_rating: null,
            lowest_rating: null,
          },
          crossovers: [
            {
              id: 3,
              name: 'Annihilation',
              applies_to_current_issue: true,
              membership_kind: 'issue',
              next_member: null,
              average_rating: 4.0,
              ratings_count: 3,
              read_count: 5,
            },
          ],
          local_chain: { issues: [], edges: [] },
        }}
        isLoading={false}
      />,
    )
    expect(screen.getByTestId('crossover-analytics')).toHaveTextContent(
      'Annihilation',
    )
  })

  it('does not show loading skeleton when loaded', () => {
    const { container } = render(
      <YourContextPillar
        activeRatingThread={ratingThread()}
        currentDie={6}
        rating={3.0}
        predictedDie={8}
        onUpdateRating={vi.fn()}
        readerContext={null}
        isLoading={false}
      />,
    )
    expect(container.querySelectorAll('.animate-pulse').length).toBe(0)
  })

  it('does not disable rating slider when context is loading', () => {
    render(
      <YourContextPillar
        activeRatingThread={ratingThread()}
        currentDie={6}
        rating={3.0}
        predictedDie={8}
        onUpdateRating={vi.fn()}
        readerContext={null}
        isLoading={true}
      />,
    )
    const slider = screen.getByRole('slider')
    expect(slider).not.toBeDisabled()
  })

  it('does not disable rating slider when context has error', () => {
    render(
      <YourContextPillar
        activeRatingThread={ratingThread()}
        currentDie={6}
        rating={3.0}
        predictedDie={8}
        onUpdateRating={vi.fn()}
        readerContext={null}
        isLoading={false}
      />,
    )
    const slider = screen.getByRole('slider')
    expect(slider).not.toBeDisabled()
  })

  it('hides skeleton and panels when not loading and no context', () => {
    render(
      <YourContextPillar
        activeRatingThread={ratingThread()}
        currentDie={6}
        rating={3.0}
        predictedDie={8}
        onUpdateRating={vi.fn()}
        readerContext={null}
        isLoading={false}
      />,
    )
    expect(screen.queryByTestId('series-panel')).not.toBeInTheDocument()
    expect(screen.queryByTestId('crossover-analytics')).not.toBeInTheDocument()
  })

  it('still renders the pillar header and rating section', () => {
    render(
      <YourContextPillar
        activeRatingThread={ratingThread()}
        currentDie={6}
        rating={3.0}
        predictedDie={8}
        onUpdateRating={vi.fn()}
        readerContext={null}
        isLoading={false}
      />,
    )
    expect(screen.queryByText('03')).not.toBeInTheDocument()
    expect(screen.getByText('Your Context')).toBeInTheDocument()
    expect(screen.getByText('Your rating')).toBeInTheDocument()
    expect(screen.getByText('3.0')).toBeInTheDocument()
  })

  it('shows last-issue banner when issues_remaining is 1', () => {
    render(
      <YourContextPillar
        activeRatingThread={ratingThread({ issues_remaining: 1 })}
        currentDie={6}
        rating={3.0}
        predictedDie={8}
        onUpdateRating={vi.fn()}
        readerContext={null}
        isLoading={false}
      />,
    )
    expect(screen.getByText(/last issue in the thread/)).toBeInTheDocument()
  })

  it('shows die consequence info', () => {
    render(
      <YourContextPillar
        activeRatingThread={ratingThread()}
        currentDie={6}
        rating={4.0}
        predictedDie={4}
        onUpdateRating={vi.fn()}
        readerContext={null}
        isLoading={false}
      />,
    )
    expect(screen.getByText('d6 → d4')).toBeInTheDocument()
    expect(screen.getByText('More focused next roll')).toBeInTheDocument()
  })
})
