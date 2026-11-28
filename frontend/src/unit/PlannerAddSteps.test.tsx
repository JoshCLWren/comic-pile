import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import PlannerAddSteps from '../pages/continuity-planner/PlannerAddSteps'
import type { ContinuityPlannerEditor } from '../pages/continuity-planner/useContinuityPlannerEditor'
import type { PlannerLane } from '../pages/continuity-planner/plannerModel'
import type { Issue, ThreadListItem } from '../types'

const lane: PlannerLane = { id: 'main', name: 'Reading order', order: 0 }

// SAFETY: test fixture supplies only the fields the selector reads
const issues = [
  { id: 11, issue_number: 'Annual 1' },
  { id: 12, issue_number: '1/2' },
] as Issue[]

// SAFETY: test fixture supplies only the fields the selector reads
const threads = [
  {
    id: 4,
    title: 'Mister Miracle',
    issues_remaining: 2,
    total_issues: 2,
    queue_position: 1,
    status: 'active',
    is_blocked: false,
    blocking_reasons: [],
    last_activity_at: null,
    created_at: '2026-01-01T00:00:00Z',
  },
] as ThreadListItem[]

function makeEditor(overrides: Partial<ContinuityPlannerEditor> = {}): ContinuityPlannerEditor {
  return {
    name: 'Saved lane',
    orderingMode: 'informational',
    lanes: [lane],
    orderedLanes: [lane],
    nodes: [],
    activeLaneId: lane.id,
    targetLaneId: lane.id,
    selectedThread: null,
    selectedThreadId: null,
    selectedIssue: null,
    selectedGroupId: '',
    saveError: null,
    cblCommitPending: false,
    isProjectionOpen: false,
    editingGateNodeId: null,
    lastPlanId: null,
    savedName: 'Saved lane',
    isDirty: false,
    isSaving: false,
    statusText: null,
    sourcePaths: [],
    saveMutationPending: false,
    setName: vi.fn(),
    setOrderingMode: vi.fn(),
    setActiveLaneId: vi.fn(),
    setSelectedIssue: vi.fn(),
    setSelectedGroupId: vi.fn(),
    setCblCommitPending: vi.fn(),
    setIsProjectionOpen: vi.fn(),
    setEditingGateNodeId: vi.fn(),
    selectThread: vi.fn(),
    addIssue: vi.fn(),
    addCrossover: vi.fn(),
    moveInLane: vi.fn(),
    moveToLane: vi.fn(),
    removeNode: vi.fn(),
    toggleCheckpoint: vi.fn(),
    toggleConvergenceGate: vi.fn(),
    addLane: vi.fn(),
    renameLane: vi.fn(),
    moveLane: vi.fn(),
    removeLane: vi.fn(),
    save: vi.fn(),
    cancel: vi.fn(),
    acceptCommittedPlan: vi.fn(),
    ...overrides,
  }
}

describe('PlannerAddSteps', () => {
  it('keeps the issue picker and every option usable when lanes and issues exist (#3607)', async () => {
    const editor = makeEditor({ selectedIssue: null, selectedThread: null })
    const user = userEvent.setup()
    render(
      <PlannerAddSteps
        editor={editor}
        threads={threads}
        issues={issues}
        issuesLoading={false}
        issueLoadError={null}
        groups={[]}
      />,
    )

    // Availability of the issue picker is lane-driven. The selector's own
    // loading/empty guards still apply, but a separate thread-selection flag
    // must never disable issues that are loaded and selectable.
    const issueSelect = screen.getByLabelText('Issue')
    expect(issueSelect).toBeEnabled()
    const options = within(issueSelect).getAllByRole('option')
    expect(options.length).toBeGreaterThan(1)
    for (const option of options) {
      expect(option).not.toBeDisabled()
    }

    await user.selectOptions(issueSelect, '11')
    expect(editor.setSelectedIssue).toHaveBeenCalledWith(issues[0])
  })

  it('disables the issue picker when the plan has no lane', () => {
    render(
      <PlannerAddSteps
        editor={makeEditor({ lanes: [], orderedLanes: [] })}
        threads={threads}
        issues={issues}
        issuesLoading={false}
        issueLoadError={null}
        groups={[]}
      />,
    )

    expect(screen.getByLabelText('Issue')).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Add issue' })).toBeDisabled()
  })

  it('treats a series with issues remaining but no issue records as empty (#4119)', () => {
    // The remaining count is deliberately independent of the issue records:
    // this series reports one issue left but has zero issue records to plan.
    const emptySeries = { ...threads[0], issues_remaining: 1 }
    const editor = makeEditor({
      selectedThread: emptySeries,
      selectedThreadId: emptySeries.id,
    })
    render(
      <PlannerAddSteps
        editor={editor}
        threads={[emptySeries]}
        issues={[]}
        issuesLoading={false}
        issueLoadError={null}
        groups={[]}
      />,
    )

    const issueSelect = screen.getByLabelText('Issue')
    expect(issueSelect).toBeDisabled()
    const options = within(issueSelect).getAllByRole('option')
    expect(options).toHaveLength(1)
    expect(options[0]).toHaveTextContent('No issues available')
    expect(screen.getByRole('button', { name: 'Add issue' })).toBeDisabled()
    expect(screen.getByRole('status')).toHaveTextContent(
      /No issues in this series yet/i,
    )
  })

  it('does not add a stale issue for a series with no issue records (#4119)', () => {
    const emptySeries = { ...threads[0], issues_remaining: 1 }
    const editor = makeEditor({
      selectedThread: emptySeries,
      selectedThreadId: emptySeries.id,
      // A selection left over from a different series must not create a step.
      selectedIssue: issues[0],
    })
    render(
      <PlannerAddSteps
        editor={editor}
        threads={[emptySeries]}
        issues={[]}
        issuesLoading={false}
        issueLoadError={null}
        groups={[]}
      />,
    )

    fireEvent.submit(screen.getByRole('form', { name: 'Add an issue' }))
    expect(editor.addIssue).not.toHaveBeenCalled()
  })

  it('adds an issue that is present in the loaded issue set', () => {
    const editor = makeEditor({
      selectedThread: threads[0],
      selectedThreadId: threads[0].id,
      selectedIssue: issues[0],
    })
    render(
      <PlannerAddSteps
        editor={editor}
        threads={threads}
        issues={issues}
        issuesLoading={false}
        issueLoadError={null}
        groups={[]}
      />,
    )

    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Add issue' }))
    expect(editor.addIssue).toHaveBeenCalledTimes(1)
  })
})
