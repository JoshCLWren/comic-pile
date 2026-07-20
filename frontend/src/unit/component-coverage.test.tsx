import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import MigrationDialog from '../components/MigrationDialog'
import PositionSlider from '../components/PositionSlider'
import ReadingOrderTimeline from '../components/ReadingOrderTimeline'
import LoadingSpinner from '../components/LoadingSpinner'
import { MarqueeTitle } from '../components/MarqueeTitle'

const migrate = vi.hoisted(() => vi.fn())
vi.mock('../services/api', () => ({ migrationApi: { migrateThread: migrate } }))

const thread = { id: 1, title: 'Saga' }

describe('small and dialog components', () => {
  it('renders spinner variants and marquee title', () => {
    expect(render(<LoadingSpinner message="Working" fullScreen size="lg" />).getByRole('status')).toBeInTheDocument()
    render(<LoadingSpinner message="" size="sm" />)
    const { container } = render(<MarqueeTitle title="Short" />)
    expect(container.textContent).toContain('Short')
  })

  it('validates migration fields, previews warnings, skips, and submits', async () => {
    migrate.mockResolvedValue({ ...thread, total_issues: 10 })
    const onComplete = vi.fn(); const onSkip = vi.fn(); const onClose = vi.fn()
    const user = userEvent.setup()
    render(<MigrationDialog thread={thread} onComplete={onComplete} onSkip={onSkip} onClose={onClose} />)
    await user.click(screen.getByRole('button', { name: 'Start Tracking' }))
    expect(screen.getByRole('alert')).toHaveTextContent('fill in both')
    await user.type(screen.getByRole('spinbutton', { name: /Last Issue Read/ }), '10')
    await user.type(screen.getByRole('spinbutton', { name: /Total Issues/ }), '5')
    await user.click(screen.getByRole('button', { name: 'Start Tracking' }))
    expect(screen.getByRole('alert')).toHaveTextContent('cannot exceed')
    await user.clear(screen.getByRole('spinbutton', { name: /Last Issue Read/ })); await user.clear(screen.getByRole('spinbutton', { name: /Total Issues/ }))
    await user.type(screen.getByRole('spinbutton', { name: /Last Issue Read/ }), '0'); await user.type(screen.getByRole('spinbutton', { name: /Total Issues/ }), '10')
    expect(screen.getByRole('status')).toHaveTextContent('Starting fresh')
    expect(screen.getByText(/all 10 issues/i)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Start Tracking' }))
    await waitFor(() => expect(onComplete).toHaveBeenCalled())
    await user.click(screen.getByRole('button', { name: 'Skip' }))
    await user.click(screen.getByRole('button', { name: 'Yes, Skip' }))
    expect(onSkip).toHaveBeenCalled()
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(onClose).toHaveBeenCalled()
  })

  it('handles migration API errors and skip cancellation', async () => {
    migrate.mockRejectedValueOnce(new Error('Nope'))
    const user = userEvent.setup()
    render(<MigrationDialog thread={thread} onComplete={vi.fn()} onSkip={vi.fn()} onClose={vi.fn()} />)
    await user.type(screen.getByRole('spinbutton', { name: /Last Issue Read/ }), '1'); await user.type(screen.getByRole('spinbutton', { name: /Total Issues/ }), '2')
    await user.click(screen.getByRole('button', { name: 'Start Tracking' }))
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Nope'))
    await user.click(screen.getByRole('button', { name: 'Skip' }))
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByText('Skip migration?')).not.toBeInTheDocument()
  })

  it('moves a thread through slider positions and cancels', async () => {
    const onPositionSelect = vi.fn(); const onCancel = vi.fn()
    const threads = [{ id: 2, title: 'A very long title that should truncate here', queue_position: 2 }, { id: 1, title: 'Current', queue_position: 1 }, { id: 3, title: 'Third', queue_position: 3 }]
    const user = userEvent.setup()
    render(<PositionSlider threads={threads} currentThread={threads[1]} onPositionSelect={onPositionSelect} onCancel={onCancel} />)
    const slider = screen.getByRole('slider')
    expect(screen.getByText('Current position (no change)')).toBeInTheDocument()
    fireEvent.change(slider, { target: { value: '2' } })
    expect(screen.getByText('Move to back of queue')).toBeInTheDocument()
    await user.click(screen.getByTestId('position-slider-confirm'))
    expect(onPositionSelect).toHaveBeenCalledWith(3)
    await user.click(screen.getByTestId('position-slider-cancel'))
    expect(onCancel).toHaveBeenCalled()
  })

  it('covers front, between, before, after, and long-title slider contexts', () => {
    const threads = [
      { id: 1, title: 'Current', queue_position: 1 },
      { id: 2, title: 'A title that is definitely longer than twenty characters', queue_position: 2 },
      { id: 3, title: 'Third', queue_position: 3 },
      { id: 4, title: 'Fourth', queue_position: 4 },
    ]
    render(<PositionSlider threads={threads} currentThread={threads[1]} onPositionSelect={vi.fn()} onCancel={vi.fn()} />)
    const slider = screen.getByRole('slider')
    fireEvent.change(slider, { target: { value: '0' } })
    expect(screen.getByText('Move to front of queue')).toBeInTheDocument()
    fireEvent.change(slider, { target: { value: '3' } })
    expect(screen.getByText('Move to back of queue')).toBeInTheDocument()
    fireEvent.change(slider, { target: { value: '2' } })
    expect(screen.getByText(/Before|Between|After/)).toBeInTheDocument()
  })

  it('renders reading timeline empty and populated states', () => {
    render(<ReadingOrderTimeline thread={null} dependencies={[]} />)
    expect(screen.getByText(/Select a thread/)).toBeInTheDocument()
    render(<ReadingOrderTimeline thread={{ ...thread, issues_remaining: 0, total_issues: null, next_unread_issue_number: null } as never} dependencies={[]} />)
    expect(screen.getByText('Completed')).toBeInTheDocument()
    expect(screen.getByText(/more precise/)).toBeInTheDocument()
  })

  it('renders gate and span timeline cards for blocked, satisfied, and dormant gates', () => {
    const timelineThread = {
      ...thread,
      id: 1,
      issues_remaining: 5,
      total_issues: 12,
      next_unread_issue_id: 101,
      next_unread_issue_number: '2',
    }
    const dependencies = [
      { id: 1, source_thread_id: 2, target_thread_id: null, source_issue_id: 1, target_issue_id: 101, source_label: 'Source #1', target_label: 'Target #2', target_issue_thread_id: 1, source_issue_thread_id: 2, is_issue_level: true, created_at: 'now' },
      { id: 2, source_thread_id: 3, target_thread_id: null, source_issue_id: 2, target_issue_id: 104, source_label: 'Other #2', target_label: 'Target #5', target_issue_thread_id: 1, source_issue_thread_id: 3, is_issue_level: true, created_at: 'now' },
    ]
    render(<ReadingOrderTimeline thread={timelineThread as never} dependencies={dependencies as never} />)
    expect(screen.getAllByText('Issue #2').length).toBeGreaterThan(0)
    expect(screen.getByText('Blocked')).toBeInTheDocument()
    expect(screen.getByText('Dormant')).toBeInTheDocument()
    expect(screen.getByText('Issues 1–1')).toBeInTheDocument()
    expect(screen.getByText('Issues 6–12')).toBeInTheDocument()
  })

  it('renders unknown reading position and a single prerequisite gate', () => {
    render(<ReadingOrderTimeline
      thread={{ ...thread, issues_remaining: 3, total_issues: 5, next_unread_issue_number: null, next_unread_issue_id: 100 } as never}
      dependencies={[{
        id: 9, source_thread_id: 2, target_thread_id: null, source_issue_id: 2, target_issue_id: 100,
        source_label: 'Prerequisite #2', target_label: 'Target', target_issue_thread_id: 1,
        source_issue_thread_id: 2, is_issue_level: true, created_at: 'now',
      }] as never}
    />)
    expect(screen.getByText('Unknown')).toBeInTheDocument()
    expect(screen.getByText('Prerequisite:')).toBeInTheDocument()
  })

  it('renders current spans and safe gate labels for sparse issue metadata', () => {
    render(<ReadingOrderTimeline
      thread={{ ...thread, id: 1, issues_remaining: 2, total_issues: 6, next_unread_issue_number: '4', next_unread_issue_id: 104 } as never}
      dependencies={[{
        id: 10, source_thread_id: 2, target_thread_id: null, source_issue_id: 2, target_issue_id: 104,
        source_label: 'Prerequisite', target_label: null, target_issue_thread_id: 1,
        source_issue_thread_id: 2, is_issue_level: true, created_at: 'now',
      }, {
        id: 11, source_thread_id: 3, target_thread_id: null, source_issue_id: 3, target_issue_id: 104,
        source_label: 'Another prerequisite', target_label: null, target_issue_thread_id: 1,
        source_issue_thread_id: 3, is_issue_level: true, created_at: 'now',
      }] as never}
    />)
    expect(screen.getByText('Issue #104')).toBeInTheDocument()
    expect(screen.getByText('Issue gate')).toBeInTheDocument()
    expect(screen.getByText('Current position')).toBeInTheDocument()
    expect(screen.getByText('You are here')).toBeInTheDocument()
  })

})
