import type { PropsWithChildren } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, act, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it } from 'vitest'
import type { ContinuityPlan } from '../services/api-continuity-plans'
import {
  useContinuityPlannerEditor,
  type ContinuityPlannerEditorInputs,
} from '../pages/continuity-planner/useContinuityPlannerEditor'

const thread = {
  id: 4,
  title: 'Mister Miracle',
  format: 'single issues',
  issues_remaining: 12,
  total_issues: 12,
  queue_position: 1,
  status: 'active',
  is_blocked: false,
  blocking_reasons: [],
  created_at: '2026-08-12T00:00:00Z',
}

const issue = {
  id: 40,
  thread_id: 4,
  issue_number: 'Annual 1',
  position: 1,
  status: 'unread',
  read_at: null,
  created_at: '2026-08-12T00:00:00Z',
}

const group = {
  id: 8,
  name: 'Fourth World',
  memberships: [],
  created_at: '2026-08-12T00:00:00Z',
}

const savedPlan = {
  id: 12,
  user_id: 1,
  name: 'Kirby lane',
  ordering_mode: 'informational',
  lanes: [{ id: 'main', name: 'Reading order', order: 0 }],
  nodes: [
    {
      id: 'issue-40',
      node_type: 'issue',
      ref_id: 40,
      lane_id: 'main',
      position: 0,
      label: 'Mister Miracle #Annual 1',
    },
  ],
  created_at: '2026-08-12T00:00:00Z',
  updated_at: '2026-08-12T00:00:00Z',
} as ContinuityPlan

let queryClient: QueryClient

function wrapper({ children }: PropsWithChildren) {
  return (
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/continuity-plans']}>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

const baseInputs: ContinuityPlannerEditorInputs = {
  planId: null,
  planData: undefined,
  planPending: false,
  groups: [],
  groupsPending: false,
  threadsPending: false,
  isInvalidRoute: false,
  addFromCblRequested: false,
}

beforeEach(() => {
  queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
})

describe('useContinuityPlannerEditor', () => {
  it('hydrates a persisted plan into draft state without dirty changes', async () => {
    const { result } = renderHook(
      ({ inputs }: { inputs: ContinuityPlannerEditorInputs }) => useContinuityPlannerEditor(inputs),
      { wrapper, initialProps: { inputs: { ...baseInputs, planId: 12, planData: savedPlan } } },
    )

    await waitFor(() => expect(result.current.nodes).toHaveLength(1))
    expect(result.current.name).toBe('Kirby lane')
    expect(result.current.isDirty).toBe(false)
    expect(result.current.statusText).toBe('Saved')
  })

  it('adds an issue step and guards against duplicates', async () => {
    const { result } = renderHook(
      ({ inputs }: { inputs: ContinuityPlannerEditorInputs }) => useContinuityPlannerEditor(inputs),
      { wrapper, initialProps: { inputs: baseInputs } },
    )

    await waitFor(() => expect(result.current.statusText).toBe('New plan'))

    act(() => {
      result.current.selectThread(thread as never)
    })
    act(() => {
      result.current.setSelectedIssue(issue as never)
    })
    act(() => {
      result.current.addIssue()
    })

    expect(result.current.nodes).toHaveLength(1)
    expect(result.current.nodes[0]).toMatchObject({
      id: 'issue-40',
      lane_id: 'main',
      position: 0,
      label: 'Mister Miracle #Annual 1',
    })
    expect(result.current.isDirty).toBe(true)

    act(() => {
      result.current.setSelectedIssue(issue as never)
    })
    act(() => {
      result.current.addIssue()
    })
    expect(result.current.nodes).toHaveLength(1)
    expect(result.current.saveError).toBe('That issue is already in this plan.')
  })

  it('adds a crossover step and guards against duplicates', async () => {
    const { result } = renderHook(
      ({ inputs }: { inputs: ContinuityPlannerEditorInputs }) => useContinuityPlannerEditor(inputs),
      {
        wrapper,
        initialProps: { inputs: { ...baseInputs, groups: [group] as never } },
      },
    )

    await waitFor(() => expect(result.current.statusText).toBe('New plan'))

    act(() => {
      result.current.setSelectedGroupId('8')
    })
    act(() => {
      result.current.addCrossover()
    })
    expect(result.current.nodes).toHaveLength(1)
    expect(result.current.nodes[0]).toMatchObject({ id: 'crossover-8', label: 'Fourth World' })

    act(() => {
      result.current.setSelectedGroupId('8')
    })
    act(() => {
      result.current.addCrossover()
    })
    expect(result.current.nodes).toHaveLength(1)
    expect(result.current.saveError).toBe('That crossover is already in this plan.')
  })

  it('moves nodes within a lane and removes them', async () => {
    const { result } = renderHook(
      ({ inputs }: { inputs: ContinuityPlannerEditorInputs }) => useContinuityPlannerEditor(inputs),
      { wrapper, initialProps: { inputs: { ...baseInputs, planId: 12, planData: savedPlan } } },
    )

    await waitFor(() => expect(result.current.nodes).toHaveLength(1))

    act(() => {
      result.current.selectThread(thread as never)
    })
    expect(result.current.selectedThreadId).toBe(4)

    // Move the single node: out-of-range moves are no-ops
    act(() => {
      result.current.moveInLane('issue-40', -1)
    })
    expect(result.current.nodes[0]).toMatchObject({ id: 'issue-40', position: 0 })

    act(() => {
      result.current.removeNode('issue-40')
    })
    expect(result.current.nodes).toHaveLength(0)
  })

  it('drops strict sequential ordering when a second lane is added', async () => {
    const { result } = renderHook(
      ({ inputs }: { inputs: ContinuityPlannerEditorInputs }) => useContinuityPlannerEditor(inputs),
      { wrapper, initialProps: { inputs: baseInputs } },
    )

    await waitFor(() => expect(result.current.statusText).toBe('New plan'))

    act(() => {
      result.current.setOrderingMode('strict_sequential')
    })
    expect(result.current.orderingMode).toBe('strict_sequential')

    act(() => {
      result.current.addLane()
    })
    expect(result.current.orderingMode).toBe('informational')
    expect(result.current.orderedLanes).toHaveLength(2)
  })

  it('toggles checkpoints and restores saved state on cancel', async () => {
    const { result } = renderHook(
      ({ inputs }: { inputs: ContinuityPlannerEditorInputs }) => useContinuityPlannerEditor(inputs),
      { wrapper, initialProps: { inputs: { ...baseInputs, planId: 12, planData: savedPlan } } },
    )

    await waitFor(() => expect(result.current.nodes).toHaveLength(1))

    act(() => {
      result.current.toggleCheckpoint('issue-40')
    })
    expect(result.current.nodes[0]?.is_checkpoint).toBe(true)
    expect(result.current.isDirty).toBe(true)

    act(() => {
      result.current.cancel()
    })
    expect(result.current.nodes[0]?.is_checkpoint).toBeFalsy()
    expect(result.current.isDirty).toBe(false)
    expect(result.current.saveError).toBeNull()
  })
})
