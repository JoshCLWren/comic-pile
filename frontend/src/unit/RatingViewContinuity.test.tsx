import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { RatingView } from '../pages/RollPage/components/RatingView'
vi.mock('../contexts/useToast', () => ({ useToast: () => ({ toasts: [], showToast: vi.fn(), removeToast: vi.fn() }) }))

vi.mock('../components/LazyDice3D', () => ({ default: () => <div data-testid="dice" /> }))
vi.mock('../components/Tooltip', () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))
vi.mock('../components/IssueCorrectionDialog', () => ({ default: () => null }))
vi.mock('../pages/RollPage/components/ReadingOrderGroups', () => ({
  ReadingOrderGroups: () => null,
}))

vi.mock('../hooks/useReaderContext', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../hooks/useReaderContext')>()
  return {
    ...actual,
    useReaderContext: () => ({
      context: null,
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    }),
  }
})
vi.mock('../components/ContinuityCorrectionDialog', () => ({
  default: ({
    isOpen,
    onClose,
    onSuccess,
  }: {
    isOpen: boolean
    onClose: () => void
    onSuccess: () => void
  }) =>
    isOpen ? (
      <div data-testid="continuity-correction-dialog">
        <button type="button" onClick={onClose}>
          Close continuity
        </button>
        <button type="button" onClick={onSuccess}>
          Save continuity
        </button>
      </div>
    ) : null,
}))

const callbacks = {
  onUpdateRating: vi.fn(),
  onSubmitRating: vi.fn(),
  onSnooze: vi.fn(),
  onCancel: vi.fn(),
  onRefreshThread: vi.fn(),
}

function renderRatingView(overrides: Partial<React.ComponentProps<typeof RatingView>> = {}) {
  render(
    <MemoryRouter>
      <RatingView
        activeRatingThread={{
          id: 1,
          title: 'Ultimate X-Men',
          format: 'Comic',
          issues_remaining: 4,
          total_issues: 12,
          issue_number: '11',
          next_issue_number: '12',
        queue_position: 0,
        } as never}
        currentDie={6}
        rolledResult={2}
        rating={4}
        predictedDie={4}
        errorMessage=""
        rateIsPending={false}
        snoozeIsPending={false}
        dismissIsPending={false}
        readerContext={null}
        isReaderContextLoading={false}
        {...callbacks}
        {...overrides}
      />
    </MemoryRouter>,
  )
}

afterEach(() => {
  vi.clearAllMocks()
})

describe('RatingView continuity correction retired (#2711)', () => {
  it('renders no Reading Context lazy control and no Correct continuity button', () => {
    renderRatingView()
    expect(screen.queryByTestId('reading-context-button')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /correct continuity/i })).not.toBeInTheDocument()
    expect(screen.queryByTestId('rating-region-reading-optional')).not.toBeInTheDocument()
  })

  it('does not render the Correct continuity button without an active thread', () => {
    renderRatingView({ activeRatingThread: null })
    expect(screen.queryByRole('button', { name: /correct continuity/i })).not.toBeInTheDocument()
    expect(screen.queryByTestId('reading-context-button')).not.toBeInTheDocument()
  })
})
