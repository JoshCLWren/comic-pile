import { useState } from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReadingOrder } from '../services/api-reading-orders'
import type { ConnectedThreadInfo } from '../types'
import { ReadingRouteExplanation } from '../pages/RollPage/components/ReadingRouteExplanation'

const mocks = vi.hoisted(() => ({
  useContinuityReadiness: vi.fn(),
  useContinuityChains: vi.fn(),
}))

vi.mock('../hooks/useContinuityReadiness', () => ({
  useContinuityReadiness: mocks.useContinuityReadiness,
}))
vi.mock('../hooks/useContinuityChains', () => ({
  useContinuityChains: mocks.useContinuityChains,
}))

const refetch = vi.fn()
const chainsRefetch = vi.fn()
const routes = [
  { id: 2, name: 'Secret Wars', completed_items: 2, total_items: 8 },
  { id: 1, name: 'Avengers path', completed_items: 5, total_items: 10 },
] as ReadingOrder[]
const connections = [
  { thread_id: 9, dependency_id: 4, title: 'Prelude', connection_type: 'blocked_by' as const },
] as ConnectedThreadInfo[]

function setupChains(overrides: Partial<ReturnType<typeof mocks.useContinuityChains>> = {}) {
  mocks.useContinuityChains.mockReturnValue({
    chains: {
      node_type: 'issue',
      node_id: 7,
      evaluated_issue_id: null,
      direct_blockers: [],
      chains: [],
      readable_prerequisites: [],
      diagnostics: [],
    },
    isLoading: false,
    error: null,
    refetch: chainsRefetch,
    ...overrides,
  })
}

beforeEach(() => {
  refetch.mockReset()
  chainsRefetch.mockReset()
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
  setupChains({
    chains: {
      node_type: 'issue',
      node_id: 7,
      evaluated_issue_id: null,
      direct_blockers: [{
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
      chains: [
        [
          {
            node_type: 'issue',
            node_id: 3,
            label: 'Prelude #1',
            is_readable: true,
          },
        ],
      ],
      readable_prerequisites: [
        {
          node_type: 'issue',
          node_id: 3,
          label: 'Prelude #1',
          is_readable: true,
        },
      ],
      diagnostics: [],
    },
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
    expect(screen.getAllByText('Prelude #1').length).toBeGreaterThan(0)
    expect(screen.getByText('Finish the prelude first')).toBeVisible()
    expect(screen.getByText(/membership is informational/i)).toBeVisible()
    const names = screen.getAllByRole('listitem').map((item) => item.textContent)
    expect(names.join(' ')).toMatch(/Avengers path.*Secret Wars/)
  })

  it('identifies the direct blocker and the first readable prerequisite', () => {
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

    expect(screen.getByText(/unresolved direct blockers/i)).toBeVisible()
    expect(screen.getByText('Currently readable prerequisites')).toBeVisible()
    expect(screen.getByTestId('readable-prerequisite-3')).toBeVisible()
  })

  it('renders converging parallel prerequisite lanes deterministically', () => {
    setupChains({
      chains: {
        node_type: 'issue',
        node_id: 7,
        evaluated_issue_id: null,
        direct_blockers: [
          {
            rule_id: 10,
            source_type: 'issue',
            source_id: 11,
            source_label: 'Convergence A',
            satisfaction_type: 'item_read',
            satisfied: false,
            causing_issue_ids: [11],
            causing_member_issue_ids: [],
            note: null,
          },
          {
            rule_id: 12,
            source_type: 'issue',
            source_id: 13,
            source_label: 'Convergence B',
            satisfaction_type: 'item_read',
            satisfied: false,
            causing_issue_ids: [13],
            causing_member_issue_ids: [],
            note: null,
          },
        ],
        chains: [
          [
            {
              node_type: 'issue',
              node_id: 11,
              label: 'Convergence A',
              is_readable: true,
            },
          ],
          [
            {
              node_type: 'issue',
              node_id: 13,
              label: 'Convergence B',
              is_readable: true,
            },
          ],
        ],
        readable_prerequisites: [
          {
            node_type: 'issue',
            node_id: 11,
            label: 'Convergence A',
            is_readable: true,
          },
          {
            node_type: 'issue',
            node_id: 13,
            label: 'Convergence B',
            is_readable: true,
          },
        ],
        diagnostics: [],
      },
    })

    render(
      <ReadingRouteExplanation
        isOpen
        issueId={7}
        issueLabel="Convergence target"
        readingOrders={[]}
        connectedThreads={[]}
        onClose={vi.fn()}
      />,
    )

    const lanes = screen.getByTestId('parallel-prerequisite-lanes')
    expect(lanes).toBeInTheDocument()
    expect(screen.getByTestId('prerequisite-lane-0')).toHaveTextContent('Convergence A')
    expect(screen.getByTestId('prerequisite-lane-1')).toHaveTextContent('Convergence B')
  })

  it('does not mislabel independent lanes as converging branches', () => {
    setupChains({
      chains: {
        node_type: 'issue',
        node_id: 7,
        evaluated_issue_id: null,
        direct_blockers: [],
        chains: [
          [
            {
              node_type: 'issue',
              node_id: 11,
              label: 'Convergence A',
              is_readable: true,
            },
          ],
          [
            {
              node_type: 'issue',
              node_id: 13,
              label: 'Convergence B',
              is_readable: true,
            },
          ],
        ],
        readable_prerequisites: [
          {
            node_type: 'issue',
            node_id: 11,
            label: 'Convergence A',
            is_readable: true,
          },
          {
            node_type: 'issue',
            node_id: 13,
            label: 'Convergence B',
            is_readable: true,
          },
        ],
        diagnostics: [],
      },
    })

    render(
      <ReadingRouteExplanation
        isOpen
        issueId={7}
        issueLabel="Convergence target"
        readingOrders={[]}
        connectedThreads={[]}
        onClose={vi.fn()}
      />,
    )

    expect(screen.queryByText('Converging branches')).not.toBeInTheDocument()
  })

  it('labels lanes as converging only when branches share a common leaf', () => {
    setupChains({
      chains: {
        node_type: 'issue',
        node_id: 7,
        evaluated_issue_id: null,
        direct_blockers: [],
        chains: [
          [
            {
              node_type: 'issue',
              node_id: 11,
              label: 'Convergence A',
              is_readable: true,
            },
            {
              node_type: 'issue',
              node_id: 12,
              label: 'Shared leaf',
              is_readable: true,
            },
          ],
          [
            {
              node_type: 'issue',
              node_id: 13,
              label: 'Convergence B',
              is_readable: true,
            },
            {
              node_type: 'issue',
              node_id: 12,
              label: 'Shared leaf',
              is_readable: true,
            },
          ],
        ],
        readable_prerequisites: [
          {
            node_type: 'issue',
            node_id: 12,
            label: 'Shared leaf',
            is_readable: true,
          },
        ],
        diagnostics: [],
      },
    })

    render(
      <ReadingRouteExplanation
        isOpen
        issueId={7}
        issueLabel="Convergence target"
        readingOrders={[]}
        connectedThreads={[]}
        onClose={vi.fn()}
      />,
    )

    expect(screen.getByText('Converging branches')).toBeVisible()
  })

  it('shows verified downstream unlocks separately and omits absent unlock data', () => {
    render(
      <ReadingRouteExplanation
        isOpen
        issueId={7}
        issueLabel="Avengers #7"
        readingOrders={[]}
        connectedThreads={[
          {
            thread_id: 9,
            dependency_id: 4,
            title: 'Prelude',
            connection_type: 'blocked_by',
          } as ConnectedThreadInfo,
          {
            thread_id: 21,
            dependency_id: 8,
            title: 'Secret Sequel',
            connection_type: 'blocks',
          } as ConnectedThreadInfo,
        ]}
        onClose={vi.fn()}
      />,
    )

    expect(screen.getByText('Verified downstream unlocks')).toBeVisible()
    expect(screen.getByText('Secret Sequel')).toBeVisible()
    expect(screen.getByText('Hard prerequisite threads')).toBeVisible()
    expect(screen.getByText('Prelude')).toBeInTheDocument()
  })

  it('keeps informational routes distinct from hard blockers', () => {
    render(
      <ReadingRouteExplanation
        isOpen
        issueId={7}
        issueLabel="Avengers #7"
        readingOrders={[{ id: 4, name: 'Informational path', completed_items: 0, total_items: 5 } as ReadingOrder]}
        connectedThreads={[]}
        onClose={vi.fn()}
      />,
    )

    expect(screen.getByText(/membership is informational/i)).toBeVisible()
    expect(screen.getByText('Informational path')).toBeVisible()
    expect(screen.queryByText('Verified downstream unlocks')).not.toBeInTheDocument()
  })

  it('reports a bounded cyclic diagnostic without infinite traversal', () => {
    setupChains({
      chains: {
        node_type: 'issue',
        node_id: 7,
        evaluated_issue_id: null,
        direct_blockers: [],
        chains: [],
        readable_prerequisites: [],
        diagnostics: [{
          code: 'cycle_detected',
          node_type: 'issue',
          node_id: 7,
          limit: null,
        }],
      },
    })

    render(
      <ReadingRouteExplanation
        isOpen
        issueId={7}
        issueLabel="Cycle issue"
        readingOrders={[]}
        connectedThreads={[]}
        onClose={vi.fn()}
      />,
    )

    expect(screen.getByTestId('continuity-diagnostics')).toBeVisible()
    expect(screen.getByTestId('continuity-diagnostic-cycle_detected')).toHaveTextContent(/cyclic continuity state/i)
  })

  it('reports depth and node-limit diagnostics with their configured limit', () => {
    setupChains({
      chains: {
        node_type: 'issue',
        node_id: 7,
        evaluated_issue_id: null,
        direct_blockers: [],
        chains: [],
        readable_prerequisites: [],
        diagnostics: [
          {
            code: 'depth_limit_exceeded',
            node_type: 'issue',
            node_id: 12,
            limit: 32,
          },
          {
            code: 'node_limit_exceeded',
            node_type: 'crossover',
            node_id: 5,
            limit: 500,
          },
        ],
      },
    })
    render(
      <ReadingRouteExplanation
        isOpen
        issueId={7}
        issueLabel="Large chain issue"
        readingOrders={[]}
        connectedThreads={[]}
        onClose={vi.fn()}
      />,
    )

    expect(screen.getByTestId('continuity-diagnostic-depth_limit_exceeded')).toHaveTextContent(/limit 32/)
    expect(screen.getByTestId('continuity-diagnostic-node_limit_exceeded')).toHaveTextContent(/limit 500/)
  })

  it('states no route membership when no chained, blockers or unlocks exist', () => {
    mocks.useContinuityReadiness.mockReturnValue({
      readiness: { node_type: 'issue', node_id: 7, is_readable: true, evaluated_issue_id: 7, blockers: [] },
      isLoading: false,
      error: null,
      refetch,
    })
    setupChains({
      chains: {
        node_type: 'issue',
        node_id: 7,
        evaluated_issue_id: null,
        direct_blockers: [],
        chains: [],
        readable_prerequisites: [],
        diagnostics: [],
      },
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
    expect(screen.getByText(/all known direct prerequisites are satisfied/i)).toBeVisible()
    expect(screen.getByTestId('no-route-membership')).toBeVisible()
  })

  it('does not claim no memberships while readiness or chains are loading', () => {
    mocks.useContinuityReadiness.mockReturnValue({
      readiness: null,
      isLoading: true,
      error: null,
      refetch,
    })
    setupChains({
      chains: null,
      isLoading: true,
      error: null,
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

    expect(screen.getByRole('status')).toHaveTextContent(/checking authoritative readiness/i)
    expect(screen.queryByTestId('no-route-membership')).not.toBeInTheDocument()
  })

  it('does not claim no memberships when the chains detail failed to load', () => {
    mocks.useContinuityReadiness.mockReturnValue({
      readiness: { node_type: 'issue', node_id: 7, is_readable: true, evaluated_issue_id: 7, blockers: [] },
      isLoading: false,
      error: null,
      refetch,
    })
    setupChains({
      chains: null,
      isLoading: false,
      error: new Error('chain detail unavailable'),
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

    expect(screen.getByText(/expanded prerequisite detail could not be loaded/i)).toBeVisible()
    expect(screen.queryByTestId('no-route-membership')).not.toBeInTheDocument()
  })

  it('shows informational route chips when an eligible issue belongs to routes separately from hard dependencies', () => {
    mocks.useContinuityReadiness.mockReturnValue({
      readiness: { node_type: 'issue', node_id: 7, is_readable: true, evaluated_issue_id: 7, blockers: [] },
      isLoading: false,
      error: null,
      refetch,
    })
    setupChains({
      chains: {
        node_type: 'issue',
        node_id: 7,
        evaluated_issue_id: null,
        direct_blockers: [],
        chains: [],
        readable_prerequisites: [],
        diagnostics: [],
      },
    })
    render(
      <ReadingRouteExplanation
        isOpen
        issueId={7}
        issueLabel="Avengers #7"
        readingOrders={routes}
        connectedThreads={[]}
        onClose={vi.fn()}
      />,
    )

    expect(screen.getByText('Currently readable')).toBeVisible()
    expect(screen.getByText(/no unresolved hard prerequisite/i)).toBeVisible()
    expect(screen.getByText('Avengers path')).toBeInTheDocument()
    expect(screen.queryByTestId('no-route-membership')).not.toBeInTheDocument()
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

  it('traps focus and restores it to the route trigger after Escape', async () => {
    function Harness() {
      const [isOpen, setIsOpen] = useState(false)
      return (
        <>
          <button type="button" onClick={() => setIsOpen(true)}>Explain route</button>
          <ReadingRouteExplanation
            isOpen={isOpen}
            issueId={7}
            issueLabel="Avengers #7"
            readingOrders={routes}
            connectedThreads={[]}
            onClose={() => setIsOpen(false)}
          />
        </>
      )
    }

    const user = userEvent.setup()
    render(<Harness />)
    const trigger = screen.getByRole('button', { name: 'Explain route' })
    await user.click(trigger)
    expect(screen.getByRole('button', { name: 'Close modal' })).toHaveFocus()

    await user.keyboard('{Escape}')
    expect(trigger).toHaveFocus()
  })

  it('covers unavailable identity, loading, and retryable readiness states', async () => {
    const { rerender } = render(
      <ReadingRouteExplanation
        isOpen
        issueId={null}
        issueLabel="Unknown issue"
        readingOrders={[]}
        connectedThreads={[]}
        onClose={vi.fn()}
      />,
    )
    expect(screen.getByText(/identity is unavailable/i)).toBeVisible()

    mocks.useContinuityReadiness.mockReturnValue({
      readiness: null,
      isLoading: true,
      error: null,
      refetch,
    })
    setupChains({
      chains: null,
      isLoading: false,
      error: null,
    })
    rerender(
      <ReadingRouteExplanation
        isOpen
        issueId={7}
        issueLabel="Avengers #7"
        readingOrders={[]}
        connectedThreads={[]}
        onClose={vi.fn()}
      />,
    )
    expect(screen.getByRole('status')).toHaveTextContent(/checking authoritative readiness/i)

    mocks.useContinuityReadiness.mockReturnValue({
      readiness: null,
      isLoading: false,
      error: new Error('offline'),
      refetch,
    })
    setupChains({
      chains: null,
      isLoading: false,
      error: null,
    })
    rerender(
      <ReadingRouteExplanation
        isOpen
        issueId={7}
        issueLabel="Avengers #7"
        readingOrders={[]}
        connectedThreads={[]}
        onClose={vi.fn()}
      />,
    )
    await userEvent.click(screen.getByRole('button', { name: /retry readiness/i }))
    expect(refetch).toHaveBeenCalledOnce()
    expect(chainsRefetch).toHaveBeenCalledOnce()
  })

  it('shows authoritative eligibility with a retryable chain-detail error', async () => {
    mocks.useContinuityReadiness.mockReturnValue({
      readiness: { node_type: 'issue', node_id: 7, is_readable: true, evaluated_issue_id: 7, blockers: [] },
      isLoading: false,
      error: null,
      refetch,
    })
    setupChains({
      chains: null,
      isLoading: false,
      error: new Error('chain detail unavailable'),
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
    expect(screen.getByText(/expanded prerequisite detail could not be loaded/i)).toBeVisible()
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /retry continuity detail/i }))
    expect(chainsRefetch).toHaveBeenCalledOnce()
    expect(refetch).not.toHaveBeenCalled()
  })

  it('explains incomplete server details for blocked readiness and zero-length route progress', () => {
    mocks.useContinuityReadiness.mockReturnValue({
      readiness: { node_type: 'issue', node_id: 7, is_readable: false, evaluated_issue_id: 7, blockers: [] },
      isLoading: false,
      error: null,
      refetch,
    })
    setupChains({
      chains: {
        node_type: 'issue',
        node_id: 7,
        evaluated_issue_id: null,
        direct_blockers: [],
        chains: [],
        readable_prerequisites: [],
        diagnostics: [],
      },
    })
    render(
      <ReadingRouteExplanation
        isOpen
        issueId={7}
        issueLabel="Avengers #7"
        readingOrders={[{ id: 3, name: 'Empty route', completed_items: 0, total_items: 0 } as ReadingOrder]}
        connectedThreads={[]}
        onClose={vi.fn()}
      />,
    )
    expect(screen.getByText(/0 of 0 complete · 0%/i)).toBeVisible()
    expect(screen.queryByTestId('no-route-membership')).not.toBeInTheDocument()
    expect(screen.getByText('Empty route')).toBeVisible()
  })

  it('does not render or lock scrolling while closed', () => {
    document.body.style.overflow = 'auto'
    render(
      <ReadingRouteExplanation
        isOpen={false}
        issueId={7}
        issueLabel="Avengers #7"
        readingOrders={routes}
        connectedThreads={connections}
        onClose={vi.fn()}
      />,
    )
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(document.body.style.overflow).toBe('auto')
  })

  it('handles 422 chain detail error and shows retry button', async () => {
    mocks.useContinuityReadiness.mockReturnValue({
      readiness: { node_type: 'issue', node_id: 7, is_readable: true, evaluated_issue_id: 7, blockers: [] },
      isLoading: false,
      error: null,
      refetch,
    })
    setupChains({
      chains: null,
      isLoading: false,
      error: new Error('422 Unprocessable Entity'),
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
    expect(screen.getByText(/expanded prerequisite detail could not be loaded/i)).toBeVisible()
    expect(screen.getByRole('button', { name: /retry continuity detail/i })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /retry continuity detail/i }))
    expect(chainsRefetch).toHaveBeenCalledOnce()
  })
})
