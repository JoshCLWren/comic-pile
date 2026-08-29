import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { RatingView } from '../pages/RollPage/components/RatingView'
vi.mock('../contexts/useToast', () => ({ useToast: () => ({ toasts: [], showToast: vi.fn(), removeToast: vi.fn() }) }))

vi.mock('../components/LazyDice3D', () => ({ default: () => <div data-testid="dice" /> }))
vi.mock('../components/Tooltip', () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))
vi.mock('../components/IssueCorrectionDialog', () => ({ default: () => null }))
vi.mock('../hooks/useDependencyGroups', () => ({
  useDependencyGroups: (threadId: number | null | undefined) => ({
    groups: threadId === 42 ? [{ id: 7, name: 'Cosmic bridge' }] : [],
    isLoading: false,
    error: null,
  }),
}))
vi.mock('../hooks/useRollBootstrap', () => ({
  useRollBootstrap: () => ({
    data: null,
    isPending: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
  }),
}))

vi.mock('../hooks/useReaderContext', () => ({
  useReaderContext: () => ({
    context: null,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  }),
}))

const callbacks = {
  onUpdateRating: vi.fn(),
  onSubmitRating: vi.fn(),
  onSnooze: vi.fn(),
  onCancel: vi.fn(),
  onRefreshThread: vi.fn(),
}

function renderRatingView(
  activeRatingThread: Parameters<typeof RatingView>[0]['activeRatingThread'],
  overrides: Partial<Parameters<typeof RatingView>[0]> = {},
) {
  return render(
    <MemoryRouter>
      <RatingView
        activeRatingThread={activeRatingThread}
        currentDie={6}
        rolledResult={activeRatingThread ? 3 : null}
        rating={activeRatingThread ? 4 : 3}
        predictedDie={activeRatingThread ? 4 : 6}
        errorMessage=""
        rateIsPending={false}
        snoozeIsPending={false}
        dismissIsPending={false}
        readingOrders={overrides.readingOrders ?? []}
        connectedThreads={overrides.connectedThreads ?? []}
        {...callbacks}
      />
    </MemoryRouter>,
  )
}

describe('RatingView crossovers', () => {
  it('shows crossover names owned by the active rating thread', () => {
    renderRatingView(
      {
        id: 42,
        title: 'Silver Surfer',
        format: 'Comic',
        issues_remaining: 3,
        total_issues: 6,
        issue_number: '3',
        next_issue_number: '4',
      } as never,
      {
        readingOrders: [
          {
            id: 1,
            name: 'Main route',
            description: null,
            total_items: 2,
            completed_items: 1,
            items: [],
          },
        ],
      },
    )

    expect(screen.getByRole('heading', { name: 'Crossovers' })).toBeInTheDocument()
    expect(screen.getByText('Cosmic bridge')).toBeInTheDocument()
  })

  it('does not show crossover chrome without an active thread', () => {
    renderRatingView(null)

    expect(screen.queryByRole('heading', { name: 'Crossovers' })).not.toBeInTheDocument()
  })
})
