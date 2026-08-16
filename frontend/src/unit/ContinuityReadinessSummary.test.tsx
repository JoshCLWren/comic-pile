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
    expect(screen.getByRole('heading', { name: 'Ready to read' })).toBeVisible()

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
})
