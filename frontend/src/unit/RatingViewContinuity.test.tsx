import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { RatingView } from '../pages/RollPage/components/RatingView'
import type { ConnectedThreadInfo } from '../types'
vi.mock('../contexts/useToast', () => ({ useToast: () => ({ toasts: [], showToast: vi.fn(), removeToast: vi.fn() }) }))

vi.mock('../components/LazyDice3D', () => ({ default: () => <div data-testid="dice" /> }))
vi.mock('../components/Tooltip', () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))
vi.mock('../components/IssueCorrectionDialog', () => ({ default: () => null }))
vi.mock('../pages/RollPage/components/ReadingOrderGroups', () => ({
  ReadingOrderGroups: () => null,
}))
vi.mock('../hooks/useContinuityReadiness', () => ({
  useContinuityReadiness: () => ({
    readiness: null,
    isLoading: false,
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

const connectedThread: ConnectedThreadInfo = {
  thread_id: 99,
  title: 'Ultimate Wolverine',
  connection_type: 'blocks & blocked_by',
  dependency_id: 12,
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
        } as never}
        currentDie={6}
        rolledResult={2}
        rating={4}
        predictedDie={4}
        errorMessage=""
        rateIsPending={false}
        snoozeIsPending={false}
        dismissIsPending={false}
        readingOrders={[]}
        connectedThreads={[connectedThread]}
        {...callbacks}
        {...overrides}
      />
    </MemoryRouter>,
  )
}

afterEach(() => {
  vi.clearAllMocks()
})

describe('RatingView continuity correction', () => {
  it('renders the Correct continuity button when connected threads exist', () => {
    renderRatingView()
    expect(
      screen.getByRole('button', { name: /correct continuity/i }),
    ).toBeInTheDocument()
  })

  it('does not render the Correct continuity button without connected threads', () => {
    renderRatingView({ connectedThreads: [] })
    expect(
      screen.queryByRole('button', { name: /correct continuity/i }),
    ).not.toBeInTheDocument()
  })

  it('opens the continuity correction dialog when the button is clicked', async () => {
    const user = userEvent.setup()
    renderRatingView()
    expect(screen.queryByTestId('continuity-correction-dialog')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /correct continuity/i }))

    expect(await screen.findByTestId('continuity-correction-dialog')).toBeInTheDocument()
  })

  it('closes the continuity correction dialog via the close callback', async () => {
    const user = userEvent.setup()
    renderRatingView()
    await user.click(screen.getByRole('button', { name: /correct continuity/i }))

    await user.click(screen.getByRole('button', { name: 'Close continuity' }))

    expect(screen.queryByTestId('continuity-correction-dialog')).not.toBeInTheDocument()
  })

  it('refreshes the thread and closes the dialog when the save callback fires', async () => {
    const user = userEvent.setup()
    renderRatingView()
    await user.click(screen.getByRole('button', { name: /correct continuity/i }))

    await user.click(screen.getByRole('button', { name: 'Save continuity' }))

    expect(callbacks.onRefreshThread).toHaveBeenCalledTimes(1)
    expect(screen.queryByTestId('continuity-correction-dialog')).not.toBeInTheDocument()
  })

  it('does not render the Correct continuity button when no active thread exists', () => {
    renderRatingView({ activeRatingThread: null })
    expect(
      screen.queryByRole('button', { name: /correct continuity/i }),
    ).not.toBeInTheDocument()
  })
})
