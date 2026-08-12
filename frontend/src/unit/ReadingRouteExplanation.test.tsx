import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReadingOrder } from '../services/api-reading-orders'
import type { ConnectedThreadInfo } from '../types'
import { ReadingRouteExplanation } from '../pages/RollPage/components/ReadingRouteExplanation'

const mocks = vi.hoisted(() => ({ useContinuityReadiness: vi.fn() }))

vi.mock('../hooks/useContinuityReadiness', () => ({
  useContinuityReadiness: mocks.useContinuityReadiness,
}))

const refetch = vi.fn()
const routes = [
  { id: 2, name: 'Secret Wars', completed_items: 2, total_items: 8 },
  { id: 1, name: 'Avengers path', completed_items: 5, total_items: 10 },
] as ReadingOrder[]
const connections = [
  { thread_id: 9, dependency_id: 4, title: 'Prelude' },
] as ConnectedThreadInfo[]

beforeEach(() => {
  refetch.mockReset()
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
        note: 'Finish the prelude first',
      }],
    },
    isLoading: false,
    error: null,
    refetch,
  })
})

describe('ReadingRouteExplanation', () => {
  it('keeps hard blockers distinct from deterministic informational routes', () => {
    render(
      <ReadingRouteExplanation
        isOpen
        issueId={7}
        issueLabel="Avengers #7"
        readingOrders={routes}
        connectedThreads={connections}
        onClose={vi.fn()}
      />,
    )

    expect(screen.getByRole('dialog', { name: 'Avengers #7' })).toBeVisible()
    expect(screen.getByText('Prelude #1')).toBeVisible()
    expect(screen.getByText('Finish the prelude first')).toBeVisible()
    expect(screen.getByText(/membership is informational/i)).toBeVisible()
    const names = screen.getAllByRole('listitem').map((item) => item.textContent)
    expect(names.join(' ')).toMatch(/Avengers path.*Secret Wars/)
  })

  it('dismisses with Escape without changing the pending rating state', async () => {
    const onClose = vi.fn()
    render(
      <ReadingRouteExplanation
        isOpen
        issueId={7}
        issueLabel="Avengers #7"
        readingOrders={routes}
        connectedThreads={[]}
        onClose={onClose}
      />,
    )

    await userEvent.setup().keyboard('{Escape}')
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('states when an eligible issue has no unresolved hard prerequisites', () => {
    mocks.useContinuityReadiness.mockReturnValue({
      readiness: { node_type: 'issue', node_id: 7, is_readable: true, evaluated_issue_id: 7, blockers: [] },
      isLoading: false,
      error: null,
      refetch,
    })
    render(
      <ReadingRouteExplanation
        isOpen
        issueId={7}
        issueLabel="Avengers #7"
        readingOrders={[]}
        connectedThreads={[]}
        onClose={vi.fn()}
      />,
    )
    expect(screen.getByText('Currently readable')).toBeVisible()
    expect(screen.getByText(/no unresolved hard prerequisite/i)).toBeVisible()
  })
})
