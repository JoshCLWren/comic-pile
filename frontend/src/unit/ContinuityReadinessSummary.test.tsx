import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ContinuityReadinessSummary } from '../pages/RollPage/components/ContinuityReadinessSummary'

const mocks = vi.hoisted(() => ({ useContinuityReadiness: vi.fn() }))

vi.mock('../hooks/useContinuityReadiness', () => ({
  useContinuityReadiness: mocks.useContinuityReadiness,
}))

const refetch = vi.fn()

beforeEach(() => {
  refetch.mockReset()
})

describe('ContinuityReadinessSummary', () => {
  it('explains missing identity and loading states', () => {
    mocks.useContinuityReadiness.mockReturnValue({
      readiness: null, isLoading: false, error: null, refetch,
    })
    const { rerender } = render(<ContinuityReadinessSummary issueId={null} />)
    expect(screen.getByRole('heading', { name: 'Readiness unavailable' })).toBeVisible()

    mocks.useContinuityReadiness.mockReturnValue({
      readiness: null, isLoading: true, error: null, refetch,
    })
    rerender(<ContinuityReadinessSummary issueId={7} />)
    expect(screen.getByRole('status')).toHaveTextContent('Checking reading readiness')
  })

  it('lets the reader retry a failed readiness request', async () => {
    mocks.useContinuityReadiness.mockReturnValue({
      readiness: null, isLoading: false, error: new Error('offline'), refetch,
    })
    render(<ContinuityReadinessSummary issueId={7} />)

    await userEvent.setup().click(screen.getByRole('button', { name: 'Retry readiness' }))
    expect(refetch).toHaveBeenCalledOnce()
  })

  it('hides successful readiness while preserving blocked states', () => {
    mocks.useContinuityReadiness.mockReturnValue({
      readiness: { node_type: 'issue', node_id: 7, is_readable: true, evaluated_issue_id: 7, blockers: [] },
      isLoading: false, error: null, refetch,
    })
    const { rerender } = render(<ContinuityReadinessSummary issueId={7} />)
    expect(screen.queryByRole('heading', { name: 'Ready to read' })).not.toBeInTheDocument()

    mocks.useContinuityReadiness.mockReturnValue({
      readiness: {
        node_type: 'issue',
        node_id: 7,
        is_readable: false,
        evaluated_issue_id: 7,
        blockers: [{
          rule_id: 2,
          source_type: 'issue',
          source_id: 3,
          source_label: 'Prelude #1',
          satisfaction_type: 'item_read',
          satisfied: false,
          causing_issue_ids: [3],
          causing_member_issue_ids: [],
          unread_issue_details: [{ issue_id: 3, label: 'Prelude #1' }],
          note: null,
        }],
      },
      isLoading: false, error: null, refetch,
    })
    rerender(<ContinuityReadinessSummary issueId={7} />)
    expect(screen.getByText('Prelude #1')).toBeVisible()

    mocks.useContinuityReadiness.mockReturnValue({
      readiness: { node_type: 'issue', node_id: 7, is_readable: false, evaluated_issue_id: 7, blockers: [] },
      isLoading: false, error: null, refetch,
    })
    rerender(<ContinuityReadinessSummary issueId={7} />)
    expect(screen.getByText(/returned no prerequisite details/i)).toBeVisible()
  })

  it('shows unread issue details instead of source label when available', () => {
    mocks.useContinuityReadiness.mockReturnValue({
      readiness: {
        node_type: 'issue',
        node_id: 7,
        is_readable: false,
        evaluated_issue_id: 7,
        blockers: [{
          rule_id: 5,
          source_type: 'crossover',
          source_id: 10,
          source_label: 'Crossover X',
          satisfaction_type: 'all_members_read',
          satisfied: false,
          causing_issue_ids: [],
          causing_member_issue_ids: [20, 21],
          unread_issue_details: [
            { issue_id: 20, label: 'Batman #10' },
            { issue_id: 21, label: 'Batman #11' },
          ],
          note: null,
        }],
      },
      isLoading: false, error: null, refetch,
    })
    render(<ContinuityReadinessSummary issueId={7} />)
    expect(screen.getByText('Batman #10, Batman #11')).toBeVisible()
    expect(screen.queryByText('Crossover X')).not.toBeInTheDocument()
  })

  it('falls back to source label when unread_issue_details is empty', () => {
    mocks.useContinuityReadiness.mockReturnValue({
      readiness: {
        node_type: 'issue',
        node_id: 7,
        is_readable: false,
        evaluated_issue_id: 7,
        blockers: [{
          rule_id: 6,
          source_type: 'issue',
          source_id: 4,
          source_label: 'Old Legacy Blocker',
          satisfaction_type: 'item_read',
          satisfied: false,
          causing_issue_ids: [4],
          causing_member_issue_ids: [],
          unread_issue_details: [],
          note: null,
        }],
      },
      isLoading: false, error: null, refetch,
    })
    render(<ContinuityReadinessSummary issueId={7} />)
    expect(screen.getByText('Old Legacy Blocker')).toBeVisible()
  })
})
