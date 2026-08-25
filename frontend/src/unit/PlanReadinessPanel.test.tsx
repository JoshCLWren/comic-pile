import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import PlanReadinessPanel from '../components/PlanReadinessPanel'
import type {
  ContinuityPlanNodeReadiness,
  ContinuityPlanReadinessResponse,
} from '../services/api-continuity-plans'
import { renderWithClient } from './queryTestWrapper'

const mocks = vi.hoisted(() => ({
  readiness: vi.fn(),
}))

vi.mock('../services/api-continuity-plans', () => ({
  continuityPlansApi: {
    create: vi.fn(),
    get: vi.fn(),
    update: vi.fn(),
    readiness: mocks.readiness,
  },
}))

function readinessResponse(
  overrides: Partial<ContinuityPlanReadinessResponse> = {},
): ContinuityPlanReadinessResponse {
  return {
    plan_id: 12,
    plan_name: 'Kirby lane',
    ordering_mode: 'strict_sequential',
    lanes: [{ id: 'main', name: 'Reading order', order: 0 }],
    nodes: [],
    plan_diagnostics: [],
    summary: { total: 0, readable: 0, blocked: 0, complete: 0, unavailable: 0 },
    generated_at: '2026-08-12T00:00:00Z',
    ...overrides,
  }
}

function nodeReadiness(overrides: Partial<ContinuityPlanNodeReadiness>): ContinuityPlanNodeReadiness {
  return {
    node_id: 'issue-40',
    node_type: 'issue',
    ref_id: 40,
    lane_id: 'main',
    position: 0,
    label: 'Mister Miracle #1',
    is_readable: true,
    is_complete: false,
    evaluated_issue_id: null,
    blockers: [],
    diagnostics: [],
    chains: [],
    readable_prerequisites: [],
    ...overrides,
  }
}

const blocker = {
  rule_id: 7,
  source_type: 'crossover' as const,
  source_id: 8,
  source_label: 'Fourth World',
  satisfaction_type: 'item_read' as const,
  satisfied: false as const,
  causing_issue_ids: [41],
  causing_member_issue_ids: [],
  unread_issue_details: [{ issue_id: 41, label: 'New Gods #7' }],
  note: null,
}

beforeEach(() => {
  mocks.readiness.mockReset()
})

describe('PlanReadinessPanel', () => {
  it('renders nothing without a saved plan', () => {
    renderWithClient(<PlanReadinessPanel planId={null} />)
    expect(screen.queryByTestId('plan-readiness-loading')).not.toBeInTheDocument()
    expect(mocks.readiness).not.toHaveBeenCalled()
  })

  it('shows a loading state while the first evaluation is in flight', () => {
    mocks.readiness.mockReturnValue(new Promise(() => undefined))
    renderWithClient(<PlanReadinessPanel planId={12} />)
    expect(screen.getByTestId('plan-readiness-loading')).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('Checking plan readiness…')
  })

  it('shows an error state with a retry that refetches', async () => {
    const user = userEvent.setup()
    mocks.readiness.mockRejectedValueOnce(new Error('network down'))
    mocks.readiness.mockResolvedValueOnce(readinessResponse())
    renderWithClient(<PlanReadinessPanel planId={12} />)

    await waitFor(() => expect(screen.getByTestId('plan-readiness-error')).toBeInTheDocument())
    await user.click(screen.getByTestId('plan-readiness-retry'))

    await waitFor(() =>
      expect(screen.queryByTestId('plan-readiness-error')).not.toBeInTheDocument(),
    )
    expect(mocks.readiness).toHaveBeenCalledTimes(2)
  })

  it('prompts to save when the plan has no steps yet', async () => {
    mocks.readiness.mockResolvedValueOnce(readinessResponse())
    renderWithClient(<PlanReadinessPanel planId={12} />)

    await waitFor(() => expect(screen.getByTestId('plan-readiness-empty')).toBeInTheDocument())
    expect(screen.getByText(/add reading steps and save/i)).toBeInTheDocument()
  })

  it('summarizes readable, blocked, and complete states deterministically', async () => {
    mocks.readiness.mockResolvedValueOnce(
      readinessResponse({
        nodes: [
          nodeReadiness({ node_id: 'issue-40', label: 'Mister Miracle #1', is_readable: true }),
          nodeReadiness({
            node_id: 'issue-41',
            ref_id: 41,
            label: 'Mister Miracle #2',
            is_readable: false,
            blockers: [blocker],
          }),
          nodeReadiness({
            node_id: 'issue-42',
            ref_id: 42,
            label: 'Mister Miracle #3',
            is_readable: false,
            is_complete: true,
          }),
        ],
        summary: { total: 3, readable: 1, blocked: 1, complete: 1, unavailable: 0 },
      }),
    )
    renderWithClient(<PlanReadinessPanel planId={12} />)

    const summary = await screen.findByTestId('plan-readiness-summary')
    expect(summary).toHaveTextContent('1 readable · 1 blocked · 1 complete')

    expect(screen.getByTestId('plan-node-readiness-issue-40')).toHaveAttribute(
      'data-state',
      'readable',
    )
    expect(screen.getByTestId('plan-node-readiness-issue-41')).toHaveAttribute(
      'data-state',
      'blocked',
    )
    expect(screen.getByTestId('plan-node-readiness-issue-42')).toHaveAttribute(
      'data-state',
      'complete',
    )

    expect(screen.getByText(/Waiting on New Gods #7\./)).toBeInTheDocument()
    expect(screen.getByText('Ready to read now.')).toBeInTheDocument()
    expect(screen.getByText('Every issue in this step has been read.')).toBeInTheDocument()
  })

  it('explains unread members when a blocker has no detail labels', async () => {
    mocks.readiness.mockResolvedValueOnce(
      readinessResponse({
        nodes: [
          nodeReadiness({
            node_id: 'crossover-8',
            node_type: 'crossover',
            ref_id: 8,
            label: 'Fourth World',
            is_readable: false,
            blockers: [
              {
                ...blocker,
                unread_issue_details: [],
              },
            ],
          }),
        ],
        summary: { total: 1, readable: 0, blocked: 1, complete: 0, unavailable: 0 },
      }),
    )
    renderWithClient(<PlanReadinessPanel planId={12} />)

    await screen.findByTestId('plan-node-readiness-crossover-8')
    expect(screen.getByText('Waiting on Fourth World.')).toBeInTheDocument()
  })

  it('marks dangling and cyclic references unavailable instead of crashing', async () => {
    mocks.readiness.mockResolvedValueOnce(
      readinessResponse({
        lanes: [
          { id: 'main', name: 'Reading order', order: 0 },
          { id: 'lane-2', name: 'Lane 2', order: 1 },
        ],
        nodes: [
          nodeReadiness({
            node_id: 'issue-99',
            ref_id: 99,
            label: '[deleted series] #99',
            is_readable: false,
            diagnostics: [
              { code: 'dangling_plan_reference', node_type: 'issue', node_id: 99 },
            ],
          }),
          nodeReadiness({
            node_id: 'issue-40',
            label: 'Mister Miracle #1',
            lane_id: 'lane-2',
            position: 0,
            is_readable: false,
            diagnostics: [
              { code: 'plan_cycle_detected', node_type: 'issue', node_id: 40 },
            ],
          }),
        ],
        plan_diagnostics: [
          { code: 'plan_cycle_detected', node_type: 'issue', node_id: 40 },
        ],
        summary: { total: 2, readable: 0, blocked: 0, complete: 0, unavailable: 2 },
      }),
    )
    renderWithClient(<PlanReadinessPanel planId={12} />)

    await screen.findByTestId('plan-node-readiness-issue-99')
    expect(screen.getByTestId('plan-node-readiness-issue-99')).toHaveAttribute(
      'data-state',
      'unavailable',
    )
    expect(screen.getByTestId('plan-node-readiness-issue-40')).toHaveAttribute(
      'data-state',
      'unavailable',
    )
    expect(
      screen.getByText('This step no longer exists in your library.'),
    ).toBeInTheDocument()
    expect(
      screen.getByText('This step sits on a continuity cycle and can never become readable.'),
    ).toBeInTheDocument()
    expect(screen.getByTestId('plan-readiness-diagnostics')).toBeInTheDocument()

    // Nodes group under their own lane heading.
    const laneOne = screen.getByTestId('plan-readiness-lane-main')
    expect(laneOne).toHaveTextContent('Reading order')
    expect(laneOne).toHaveTextContent('[deleted series] #99')
    const laneTwo = screen.getByTestId('plan-readiness-lane-lane-2')
    expect(laneTwo).toHaveTextContent('Lane 2')
    expect(laneTwo).toHaveTextContent('Mister Miracle #1')
  })

  it('refetches when the refresh key changes after a save', async () => {
    mocks.readiness.mockResolvedValue(readinessResponse())
    const { rerender } = renderWithClient(<PlanReadinessPanel planId={12} />)

    await waitFor(() => expect(mocks.readiness).toHaveBeenCalledTimes(1))

    rerender(<PlanReadinessPanel planId={12} refreshKey={1} />)
    await waitFor(() => expect(mocks.readiness).toHaveBeenCalledTimes(2))
  })
})
