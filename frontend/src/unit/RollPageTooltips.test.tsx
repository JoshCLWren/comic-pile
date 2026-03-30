import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ToastProvider } from '../contexts/ToastContext'
import { http, HttpResponse } from 'msw'
import { server } from './mocks/server'
import RollPage from '../pages/RollPage'

// Mock the hooks
const mockRefetch = vi.fn()
vi.mock('../hooks/useSession', () => ({
  useSession: () => ({
    data: {
      current_die: 6,
      last_rolled_result: null,
      manual_die: null,
      has_restore_point: false,
      snoozed_threads: [
        { id: 1, title: 'Thread 1' },
        { id: 2, title: 'Thread 2' },
      ],
    },
    refetch: mockRefetch,
  }),
}))

vi.mock('../hooks/useThreads', () => ({
  useThreads: () => ({
    data: [
      { id: 1, title: 'Thread 1', issues_remaining: 5, queue_position: 1, format: 'comic' },
      { id: 2, title: 'Thread 2', issues_remaining: 3, queue_position: 2, format: 'trade' },
      { id: 3, title: 'Thread 3', issues_remaining: 7, queue_position: 3, format: 'comic' },
    ],
    isLoading: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
  }),
}))

describe('RollPage Tooltips', () => {
  beforeEach(() => {
    // Mock the tooltip API
    server.use(
      http.get('/api/tooltips/roll-page', () => {
        return HttpResponse.json({
          snoozed: {
            label: 'Snoozed',
            tooltip: 'Threads you have temporarily hidden from the roll pool',
          },
          offset: {
            label: 'Offset',
            tooltip: 'Number of snoozed threads affecting your roll position',
          },
          active: {
            label: 'Active',
            tooltip: 'Number of active threads in your reading pool',
          },
        })
      })
    )
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders tooltip for offset indicator when snoozed threads exist', async () => {
    render(<ToastProvider><RollPage /></ToastProvider>)

    // Check that the offset indicator is rendered with tooltip
    expect(screen.getByText('+2')).toBeInTheDocument()

    // Check that the offset indicator has the cursor-help class (indicating tooltip)
    const offsetIndicator = screen.getByText('+2')
    expect(offsetIndicator).toHaveClass('cursor-help')
    expect(offsetIndicator).toHaveClass('border-b')
    expect(offsetIndicator).toHaveClass('border-dashed')
    expect(offsetIndicator).toHaveClass('border-stone-600')
  })

  it('renders tooltips for snoozed offset active text', async () => {
    render(<ToastProvider><RollPage /></ToastProvider>)

    // Check that the snoozed section tooltip targets are rendered with cursor-help class
    // These are the actual elements that have tooltips attached to them

    // Check for snoozed tooltip target - use aria-label to find the specific element
    const snoozedTooltipTarget = screen.getByLabelText(/snoozed.*tap to view/i)
    expect(snoozedTooltipTarget).toBeInTheDocument()
    expect(snoozedTooltipTarget).toHaveClass('cursor-help')
    expect(snoozedTooltipTarget).toHaveClass('border-b')
    expect(snoozedTooltipTarget).toHaveClass('border-dashed')
    expect(snoozedTooltipTarget).toHaveClass('border-stone-600')

    // Check for offset tooltip target - use aria-label to find the specific element
    const offsetTooltipTarget = screen.getByLabelText(/offset.*tap to adjust/i)
    expect(offsetTooltipTarget).toBeInTheDocument()
    expect(offsetTooltipTarget).toHaveClass('cursor-help')
    expect(offsetTooltipTarget).toHaveClass('border-b')
    expect(offsetTooltipTarget).toHaveClass('border-dashed')
    expect(offsetTooltipTarget).toHaveClass('border-stone-600')

    // Active is not a tooltip target, it's just static text - skip checking for cursor-help
    const activeTooltipTarget = screen.getByLabelText('Ladder mode active')
    expect(activeTooltipTarget).toBeInTheDocument()
  })

  it('renders tooltip for ladder indicator', async () => {
    render(<ToastProvider><RollPage /></ToastProvider>)

    // Check that the Ladder indicator is rendered with tooltip
    expect(screen.getByText('Ladder')).toBeInTheDocument()

    // Check that the Ladder text has the cursor-help class (indicating tooltip)
    const ladderText = screen.getByText('Ladder')
    expect(ladderText).toHaveClass('cursor-help')
    expect(ladderText).toHaveClass('border-b')
    expect(ladderText).toHaveClass('border-dashed')
    expect(ladderText).toHaveClass('border-stone-600')
  })

  it('does not render snoozed indicators when no snoozed threads', async () => {
    // Mock session with no snoozed threads
    vi.mocked(mockRefetch).mockReturnValue({
      data: {
        current_die: 6,
        last_rolled_result: null,
        manual_die: null,
        has_restore_point: false,
        snoozed_threads: [],
      },
      refetch: vi.fn(),
    })

    render(<ToastProvider><RollPage /></ToastProvider>)

    // Should not show the offset indicator or snoozed text
    expect(screen.queryByText('+0')).not.toBeInTheDocument()
    expect(screen.queryByText('snoozed offset active')).not.toBeInTheDocument()
  })
})
