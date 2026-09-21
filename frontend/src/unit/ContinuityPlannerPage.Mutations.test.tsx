import { type ComponentProps, type PropsWithChildren } from 'react'
import { render, screen, waitFor, act, cleanup } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { continuityPlansApi } from '../services/api-continuity-plans'
import { dependencyGroupsApi } from '../services/api-dependency-groups'
import { issuesApi } from '../services/api-issues'
import { threadsApi } from '../services/api'
import ContinuityPlannerPageImpl from '../pages/ContinuityPlannerPage'

interface AddMaterialProbeProps {
  commitDisabled?: boolean
  onCommitPendingChange?: (isPending: boolean) => void
}

const addMaterialProbe = vi.hoisted(() => ({
  current: null as AddMaterialProbeProps | null,
}))

function AddMaterialProbe(props: AddMaterialProbeProps) {
  addMaterialProbe.current = props
  return <div data-testid="add-material-probe" />
}

const ContinuityPlannerPage = (props: ComponentProps<typeof ContinuityPlannerPageImpl>) => (
  <ContinuityPlannerPageImpl renderAddMaterial={AddMaterialProbe} {...props} />
)

const mocks = {
  create: vi.fn(),
  list: vi.fn(),
  get: vi.fn(),
  update: vi.fn(),
  listGroups: vi.fn(),
  listIssues: vi.fn(),
  getIssue: vi.fn(),
  listThreads: vi.fn(),
  getThread: vi.fn(),
}

const _origCreate = continuityPlansApi.create
const _origList = continuityPlansApi.list
const _origGet = continuityPlansApi.get
const _origUpdate = continuityPlansApi.update
const _origGroupsList = dependencyGroupsApi.list
const _origIssuesList = issuesApi.list
const _origThreadsList = threadsApi.list
const _origThreadsGet = threadsApi.get

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })

function queryWrapper({ children }: PropsWithChildren) {
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
}

function renderNewPlanPage() {
  return render(
    <MemoryRouter initialEntries={['/continuity-plans']}>
      <Routes>
        <Route path="/continuity-plans" element={<ContinuityPlannerPage />} />
      </Routes>
    </MemoryRouter>,
    { wrapper: queryWrapper },
  )
}

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

const secondThread = {
  ...thread,
  id: 5,
  title: 'New Gods',
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

beforeEach(() => {
  addMaterialProbe.current = null
  if (typeof window !== "undefined") {
      window.localStorage.clear();
    }
  queryClient.clear()
  continuityPlansApi.create = mocks.create as never
  continuityPlansApi.list = mocks.list as never
  continuityPlansApi.get = mocks.get as never
  continuityPlansApi.update = mocks.update as never
  dependencyGroupsApi.list = mocks.listGroups as never
  issuesApi.list = mocks.listIssues as never
  threadsApi.list = mocks.listThreads as never
  threadsApi.get = mocks.getThread as never
  vi.clearAllMocks()
  mocks.create.mockReset()
  mocks.get.mockReset()
  mocks.update.mockReset()
  mocks.list.mockResolvedValue({ plans: [], next_page_token: null })
  mocks.listGroups.mockResolvedValue([{ id: 8, name: 'Fourth World', memberships: [], created_at: '2026-08-12T00:00:00Z' }])
  mocks.listIssues.mockReset()
  mocks.listIssues.mockResolvedValue({ issues: [issue], total_count: 1, page_size: 100, next_page_token: null })
  mocks.getIssue.mockResolvedValue(issue)
  mocks.listThreads.mockResolvedValue({ threads: [thread, secondThread], next_page_token: null })
  mocks.getThread.mockResolvedValue(thread)
  mocks.create.mockResolvedValue({
    id: 12,
    user_id: 1,
    name: 'Kirby lane',
    ordering_mode: 'strict_sequential',
    lanes: [{ id: 'main', name: 'Reading order', order: 0 }],
    nodes: [],
    created_at: '2026-08-12T00:00:00Z',
    updated_at: '2026-08-12T00:00:00Z',
  })
  mocks.update.mockResolvedValue({
    id: 12,
    user_id: 1,
    name: 'Saved lane',
    ordering_mode: 'strict_sequential',
    lanes: [{ id: 'main', name: 'Reading order', order: 0 }],
    nodes: [],
    created_at: '2026-08-12T00:00:00Z',
    updated_at: '2026-08-12T00:00:00Z',
  })
})

afterEach(() => {
  cleanup()
  queryClient.clear()
  continuityPlansApi.create = _origCreate
  continuityPlansApi.list = _origList
  continuityPlansApi.get = _origGet
  continuityPlansApi.update = _origUpdate
  dependencyGroupsApi.list = _origGroupsList
  issuesApi.list = _origIssuesList
  threadsApi.list = _origThreadsList
  threadsApi.get = _origThreadsGet
})

describe('ContinuityPlannerPage', () => {
  it('creates a sequential plan from shared human-facing selectors', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/continuity-plans']}>
        <Routes>
          <Route path="/continuity-plans" element={<ContinuityPlannerPage />} />
          <Route path="/continuity-plans/:id" element={<ContinuityPlannerPage />} />
        </Routes>
      </MemoryRouter>,
      { wrapper: queryWrapper },
    )

    await user.clear(await screen.findByLabelText('Plan name'))
    await user.type(screen.getByLabelText('Plan name'), 'Kirby lane')
    await user.click(screen.getByRole('radio', { name: /Strict sequential/ }))
    await user.type(screen.getByLabelText('Comic series'), 'Mister')
    await user.click(screen.getByRole('option', { name: /Mister Miracle/i }))
    await screen.findByRole('option', { name: /Annual 1/i })
    await user.selectOptions(screen.getByLabelText('Issue'), '40')
    await user.click(screen.getByRole('button', { name: 'Add issue' }))
    await user.selectOptions(screen.getByLabelText('Crossover'), '8')
    await user.click(screen.getByRole('button', { name: 'Add crossover' }))
    await user.click(screen.getByRole('button', { name: 'Save plan' }))

    await waitFor(() => expect(mocks.create).toHaveBeenCalledOnce())
    expect(mocks.create).toHaveBeenCalledWith(expect.objectContaining({
      name: 'Kirby lane',
      ordering_mode: 'strict_sequential',
      nodes: [
        expect.objectContaining({ node_type: 'issue', ref_id: 40, position: 0 }),
        expect.objectContaining({ node_type: 'crossover', ref_id: 8, position: 1 }),
      ],
    }))
  })

  it('saves informational after moving to a second lane, and disables strict mode', async () => {
    const user = userEvent.setup()
    renderNewPlanPage()

    await screen.findByRole('group', { name: 'Ordering mode' })
    await user.type(screen.getByLabelText('Comic series'), 'Mister')
    await user.click(await screen.findByRole('option', { name: /Mister Miracle/i }))
    await screen.findByRole('option', { name: /Annual 1/i })
    await user.selectOptions(screen.getByLabelText('Issue'), '40')
    await user.click(screen.getByRole('button', { name: 'Add issue' }))
    await user.click(screen.getByRole('button', { name: 'Add lane' }))

    expect(screen.getByRole('radio', { name: /Strict sequential/ })).toBeDisabled()
    expect(screen.getByText(/Strict sequential requires exactly one lane/i)).toBeVisible()

    await user.click(screen.getByRole('button', { name: 'Save plan' }))
    await waitFor(() => expect(mocks.create).toHaveBeenCalledOnce())
    // SAFETY: mock call shape matches the create API payload
    const payload = mocks.create.mock.calls[0][0] as { ordering_mode: string }
    expect(payload.ordering_mode).toBe('informational')
  })

  it('restores saved order when unsaved changes are canceled', async () => {
    mocks.get.mockResolvedValue({
      id: 12,
      user_id: 1,
      name: 'Saved lane',
      ordering_mode: 'strict_sequential',
      lanes: [{ id: 'main', name: 'Reading order', order: 0 }],
      nodes: [{ id: 'crossover-8', node_type: 'crossover', ref_id: 8, lane_id: 'main', position: 0 , label: 'Fourth World'}],
      created_at: '2026-08-12T00:00:00Z',
      updated_at: '2026-08-12T00:00:00Z',
    })
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/continuity-plans/12']}>
        <Routes>
          <Route path="/continuity-plans/:id" element={<ContinuityPlannerPage />} />
        </Routes>
      </MemoryRouter>,
      { wrapper: queryWrapper },
    )

    expect(await screen.findByRole('button', { name: 'Remove Fourth World' })).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Remove Fourth World' }))
    expect(screen.getByText('Unsaved changes')).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Cancel changes' }))
    expect(screen.getByRole('button', { name: 'Remove Fourth World' })).toBeVisible()
    expect(mocks.update).not.toHaveBeenCalled()
  })

  it('mutually excludes planner saves and CBL commits', async () => {
    mocks.get.mockResolvedValue({
      id: 12,
      user_id: 1,
      name: 'Saved lane',
      ordering_mode: 'strict_sequential',
      lanes: [{ id: 'main', name: 'Reading order', order: 0 }],
      nodes: [
        {
          id: 'crossover-8',
          node_type: 'crossover',
          ref_id: 8,
          lane_id: 'main',
          position: 0,
          label: 'Fourth World',
        },
      ],
      created_at: '2026-08-12T00:00:00Z',
      updated_at: '2026-08-12T00:00:00Z',
    })
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/continuity-plans/12']}>
        <Routes>
          <Route path="/continuity-plans/:id" element={<ContinuityPlannerPage />} />
        </Routes>
      </MemoryRouter>,
      { wrapper: queryWrapper },
    )

    await screen.findByTestId('add-material-probe')
    expect(addMaterialProbe.current?.commitDisabled).toBe(false)
    await user.click(await screen.findByRole('button', { name: 'Remove Fourth World' }))
    expect(addMaterialProbe.current?.commitDisabled).toBe(true)

    const saveButton = screen.getByRole('button', { name: 'Save plan' })
    expect(saveButton).toBeEnabled()
    act(() => addMaterialProbe.current?.onCommitPendingChange?.(true))
    expect(saveButton).toBeDisabled()
    act(() => addMaterialProbe.current?.onCommitPendingChange?.(false))
    expect(saveButton).toBeEnabled()

    await user.click(screen.getByRole('button', { name: 'Cancel changes' }))
    expect(addMaterialProbe.current?.commitDisabled).toBe(false)
  })

  it('updates an existing plan with the in-memory node order', async () => {
    mocks.get.mockResolvedValue({
      id: 12,
      user_id: 1,
      name: 'Saved lane',
      ordering_mode: 'strict_sequential',
      lanes: [{ id: 'main', name: 'Reading order', order: 0 }],
      nodes: [
        { id: 'issue-40', node_type: 'issue', ref_id: 40, lane_id: 'main', position: 0 , label: 'Mister Miracle #Annual 1'},
        { id: 'crossover-8', node_type: 'crossover', ref_id: 8, lane_id: 'main', position: 1 , label: 'Fourth World'},
      ],
      created_at: '2026-08-12T00:00:00Z',
      updated_at: '2026-08-12T00:00:00Z',
    })
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/continuity-plans/12']}>
        <Routes>
          <Route path="/continuity-plans/:id" element={<ContinuityPlannerPage />} />
        </Routes>
      </MemoryRouter>,
      { wrapper: queryWrapper },
    )

    const moveDown = await screen.findByRole('button', { name: /Move Mister Miracle #Annual 1 later/i })
    await user.click(moveDown)
    await user.click(screen.getByRole('button', { name: 'Save plan' }))

    await waitFor(() => expect(mocks.update).toHaveBeenCalledOnce())
    expect(mocks.update).toHaveBeenCalledWith(12, expect.objectContaining({
      nodes: [
        expect.objectContaining({ id: 'crossover-8', position: 0 }),
        expect.objectContaining({ id: 'issue-40', position: 1 }),
      ],
    }))
  })

  it('falls back to the default name when canceling an unsaved new plan', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/continuity-plans']}>
        <Routes>
          <Route path="/continuity-plans" element={<ContinuityPlannerPage />} />
          <Route path="/continuity-plans/:id" element={<ContinuityPlannerPage />} />
        </Routes>
      </MemoryRouter>,
      { wrapper: queryWrapper },
    )

    const nameInput = await screen.findByLabelText('Plan name')
    await user.clear(nameInput)
    await user.type(nameInput, 'Temporary name')
    await user.type(screen.getByLabelText('Comic series'), 'Mister');
    await user.click(screen.getByRole('option', { name: /Mister Miracle/i }))
    await screen.findByRole('option', { name: /Annual 1/i })
    await user.selectOptions(screen.getByLabelText('Issue'), '40')
    await user.click(screen.getByRole('button', { name: 'Add issue' }))
    await user.click(screen.getByRole('button', { name: 'Cancel changes' }))
    expect(screen.getByLabelText('Plan name')).toHaveValue('My reading plan')
  })

  it('ignores the create form when the user has not selected an issue', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/continuity-plans']}>
        <Routes>
          <Route path="/continuity-plans" element={<ContinuityPlannerPage />} />
          <Route path="/continuity-plans/:id" element={<ContinuityPlannerPage />} />
        </Routes>
      </MemoryRouter>,
      { wrapper: queryWrapper },
    )

    const addIssueButton = await screen.findByRole('button', { name: 'Add issue' })
    expect(addIssueButton).toBeDisabled()
    await user.click(addIssueButton)
    expect(mocks.create).not.toHaveBeenCalled()
  })

  it('ignores the add-crossover click when no crossover is selected', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/continuity-plans']}>
        <Routes>
          <Route path="/continuity-plans" element={<ContinuityPlannerPage />} />
          <Route path="/continuity-plans/:id" element={<ContinuityPlannerPage />} />
        </Routes>
      </MemoryRouter>,
      { wrapper: queryWrapper },
    )

    const addCrossoverButton = await screen.findByRole('button', { name: 'Add crossover' })
    expect(addCrossoverButton).toBeDisabled()
    await user.click(addCrossoverButton)
    expect(mocks.create).not.toHaveBeenCalled()
  })

  it('falls back to the default plan name when canceling an unsaved new plan without typing a name', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/continuity-plans']}>
        <Routes>
          <Route path="/continuity-plans" element={<ContinuityPlannerPage />} />
          <Route path="/continuity-plans/:id" element={<ContinuityPlannerPage />} />
        </Routes>
      </MemoryRouter>,
      { wrapper: queryWrapper },
    )

    await user.click(screen.getByRole('button', { name: 'Cancel changes' }))
    expect(screen.getByLabelText('Plan name')).toHaveValue('My reading plan')
  })

  it('saves two parallel lanes after moving a node across lanes', async () => {
    mocks.create.mockResolvedValue({
      id: 12,
      user_id: 1,
      name: 'Parallel plan',
      ordering_mode: 'informational',
      lanes: [
        { id: 'main', name: 'Reading order', order: 0 },
        { id: 'lane-1', name: 'Lane 2', order: 1 },
      ],
      nodes: [
        { id: 'issue-40', node_type: 'issue', ref_id: 40, lane_id: 'main', position: 0 , label: 'Mister Miracle #Annual 1'},
        { id: 'crossover-8', node_type: 'crossover', ref_id: 8, lane_id: 'lane-1', position: 0 , label: 'Fourth World'},
      ],
      created_at: '2026-08-12T00:00:00Z',
      updated_at: '2026-08-12T00:00:00Z',
    })

    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/continuity-plans']}>
        <Routes>
          <Route path="/continuity-plans" element={<ContinuityPlannerPage />} />
          <Route path="/continuity-plans/:id" element={<ContinuityPlannerPage />} />
        </Routes>
      </MemoryRouter>,
      { wrapper: queryWrapper },
    )

    await user.type(screen.getByLabelText('Comic series'), 'Mister');
    await user.click(await screen.findByRole('option', { name: /Mister Miracle/i }))
    await screen.findByRole('option', { name: /Annual 1/i })
    await user.selectOptions(screen.getByLabelText('Issue'), '40')
    await user.click(screen.getByRole('button', { name: 'Add issue' }))
    await user.selectOptions(screen.getByLabelText('Crossover'), '8')
    await user.click(screen.getByRole('button', { name: 'Add crossover' }))

    await user.click(screen.getByRole('button', { name: 'Add lane' }))

    await user.selectOptions(
      screen.getByRole('combobox', { name: /Move Fourth World to another lane/i }),
      'lane-1',
    )

    await user.click(screen.getByRole('button', { name: 'Save plan' }))
    await waitFor(() => expect(mocks.create).toHaveBeenCalledOnce())

    // SAFETY: mock call shape matches the create API payload with lanes
    const payload = mocks.create.mock.calls[0][0] as {
      ordering_mode: string
      lanes: Array<{ id: string }>
      nodes: Array<{ id: string; lane_id: string; position: number }>
    }
    expect(payload.ordering_mode).toBe('informational')
    expect(payload.lanes.map((lane) => lane.id)).toEqual(['main', 'lane-1'])
    expect(payload.nodes).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ id: 'issue-40', lane_id: 'main', position: 0 }),
        expect.objectContaining({ id: 'crossover-8', lane_id: 'lane-1', position: 0 }),
      ]),
    )
  })

  it('toggles checkpoint on a node and persists it on save', async () => {
    mocks.get.mockResolvedValue({
      id: 12,
      user_id: 1,
      name: 'Checkpoint plan',
      ordering_mode: 'informational',
      lanes: [
        { id: 'main', name: 'Lane A', order: 0 },
        { id: 'lane-b', name: 'Lane B', order: 1 },
      ],
      nodes: [
        { id: 'a-1', node_type: 'issue', ref_id: 40, lane_id: 'main', position: 0 , label: 'Mister Miracle #1'},
        { id: 'a-2', node_type: 'issue', ref_id: 41, lane_id: 'main', position: 1 , label: 'Mister Miracle #2'},
        { id: 'b-1', node_type: 'issue', ref_id: 42, lane_id: 'lane-b', position: 0 , label: 'New Gods #1'},
      ],
      created_at: '2026-08-12T00:00:00Z',
      updated_at: '2026-08-12T00:00:00Z',
    })
    mocks.update.mockResolvedValue({
      id: 12,
      user_id: 1,
      name: 'Checkpoint plan',
      ordering_mode: 'informational',
      lanes: [
        { id: 'main', name: 'Lane A', order: 0 },
        { id: 'lane-b', name: 'Lane B', order: 1 },
      ],
      nodes: [
        { id: 'a-1', node_type: 'issue', ref_id: 40, lane_id: 'main', position: 0 , label: 'Mister Miracle #1'},
        { id: 'a-2', node_type: 'issue', ref_id: 41, lane_id: 'main', position: 1 , label: 'Mister Miracle #2', is_checkpoint: true, convergence_gate: [] },
        { id: 'b-1', node_type: 'issue', ref_id: 42, lane_id: 'lane-b', position: 0 , label: 'New Gods #1'},
      ],
      created_at: '2026-08-12T00:00:00Z',
      updated_at: '2026-08-12T00:00:00Z',
    })

    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/continuity-plans/12']}>
        <Routes>
          <Route path="/continuity-plans/:id" element={<ContinuityPlannerPage />} />
        </Routes>
      </MemoryRouter>,
    )

    await waitFor(() => expect(screen.getByText('Mister Miracle #2')).toBeVisible())

    // Toggle checkpoint on the second node
    const checkpointButton = screen.getByRole('button', { name: /Mark Mister Miracle #2 as checkpoint/i })
    await user.click(checkpointButton)

    // Verify checkpoint badge appears
    expect(screen.getByText('Checkpoint')).toBeVisible()

    // Save and verify the checkpoint is included
    await user.click(screen.getByRole('button', { name: 'Save plan' }))
    await waitFor(() => expect(mocks.update).toHaveBeenCalledOnce())

    // SAFETY: mock call shape matches the update API payload with checkpoints
    const payload = mocks.update.mock.calls[0][1] as { nodes: Array<{ id: string; is_checkpoint?: boolean }> }
    const checkpointNode = payload.nodes.find((n) => n.id === 'a-2')
    expect(checkpointNode?.is_checkpoint).toBe(true)
  })

  it('opens convergence editor, adds a gate target, closes editor, and saves', async () => {
    mocks.get.mockResolvedValue({
      id: 12,
      user_id: 1,
      name: 'Convergence plan',
      ordering_mode: 'informational',
      lanes: [
        { id: 'main', name: 'Lane A', order: 0 },
        { id: 'lane-b', name: 'Lane B', order: 1 },
      ],
      nodes: [
        { id: 'a-1', node_type: 'issue', ref_id: 40, lane_id: 'main', position: 0 , label: 'Mister Miracle #1'},
        { id: 'b-1', node_type: 'issue', ref_id: 42, lane_id: 'lane-b', position: 0 , label: 'New Gods #1'},
      ],
      created_at: '2026-08-12T00:00:00Z',
      updated_at: '2026-08-12T00:00:00Z',
    })
    mocks.update.mockResolvedValue({
      id: 12,
      user_id: 1,
      name: 'Convergence plan',
      ordering_mode: 'informational',
      lanes: [
        { id: 'main', name: 'Lane A', order: 0 },
        { id: 'lane-b', name: 'Lane B', order: 1 },
      ],
      nodes: [
        { id: 'a-1', node_type: 'issue', ref_id: 40, lane_id: 'main', position: 0 , label: 'Mister Miracle #1'},
        { id: 'b-1', node_type: 'issue', ref_id: 42, lane_id: 'lane-b', position: 0 , label: 'New Gods #1', is_checkpoint: false, convergence_gate: [{ node_type: 'issue', node_id: 'a-1' }] },
      ],
      created_at: '2026-08-12T00:00:00Z',
      updated_at: '2026-08-12T00:00:00Z',
    })

    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/continuity-plans/12']}>
        <Routes>
          <Route path="/continuity-plans/:id" element={<ContinuityPlannerPage />} />
        </Routes>
      </MemoryRouter>,
    )

    await waitFor(() => expect(screen.getByText('New Gods #1')).toBeVisible())

    // Open convergence editor for the second node
    const convergenceButton = screen.getByRole('button', { name: /Edit convergence gate for New Gods #1/i })
    await user.click(convergenceButton)

    // Verify convergence editor is open
    expect(screen.getByTestId('convergence-editor-b-1')).toBeVisible()

    // Select the first node as a convergence target
    const checkbox = screen.getByRole('checkbox', { name: /Mister Miracle #1/i })
    await user.click(checkbox)

    // Close the editor
    await user.click(screen.getByRole('button', { name: 'Done' }))

    // Verify convergence badge appears
    expect(screen.getByText('Convergence (1)')).toBeVisible()

    // Save and verify the convergence gate is included
    await user.click(screen.getByRole('button', { name: 'Save plan' }))
    await waitFor(() => expect(mocks.update).toHaveBeenCalledOnce())

    // SAFETY: mock call shape matches the update API payload with convergence gates
    const payload = mocks.update.mock.calls[0][1] as { nodes: Array<{ id: string; convergence_gate?: Array<{ node_id: string }> }> }
    const convergenceNode = payload.nodes.find((n) => n.id === 'b-1')
    expect(convergenceNode?.convergence_gate).toHaveLength(1)
    expect(convergenceNode?.convergence_gate?.[0].node_id).toBe('a-1')
  })

  it('removes a convergence gate target and saves', async () => {
    mocks.get.mockResolvedValue({
      id: 12,
      user_id: 1,
      name: 'Convergence plan',
      ordering_mode: 'informational',
      lanes: [
        { id: 'main', name: 'Lane A', order: 0 },
        { id: 'lane-b', name: 'Lane B', order: 1 },
      ],
      nodes: [
        { id: 'a-1', node_type: 'issue', ref_id: 40, lane_id: 'main', position: 0 , label: 'Mister Miracle #1'},
        { id: 'b-1', node_type: 'issue', ref_id: 42, lane_id: 'lane-b', position: 0 , label: 'New Gods #1', is_checkpoint: false, convergence_gate: [{ node_type: 'issue', node_id: 'a-1' }] },
      ],
      created_at: '2026-08-12T00:00:00Z',
      updated_at: '2026-08-12T00:00:00Z',
    })
    mocks.update.mockResolvedValue({
      id: 12,
      user_id: 1,
      name: 'Convergence plan',
      ordering_mode: 'informational',
      lanes: [
        { id: 'main', name: 'Lane A', order: 0 },
        { id: 'lane-b', name: 'Lane B', order: 1 },
      ],
      nodes: [
        { id: 'a-1', node_type: 'issue', ref_id: 40, lane_id: 'main', position: 0 , label: 'Mister Miracle #1'},
        { id: 'b-1', node_type: 'issue', ref_id: 42, lane_id: 'lane-b', position: 0 , label: 'New Gods #1', is_checkpoint: false, convergence_gate: [] },
      ],
      created_at: '2026-08-12T00:00:00Z',
      updated_at: '2026-08-12T00:00:00Z',
    })

    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/continuity-plans/12']}>
        <Routes>
          <Route path="/continuity-plans/:id" element={<ContinuityPlannerPage />} />
        </Routes>
      </MemoryRouter>,
    )

    await waitFor(() => expect(screen.getByText('Convergence (1)')).toBeVisible())

    // Open convergence editor for the second node
    const convergenceButton = screen.getByRole('button', { name: /Edit convergence gate for New Gods #1/i })
    await user.click(convergenceButton)

    // Unselect the first node
    const checkbox = screen.getByRole('checkbox', { name: /Mister Miracle #1/i })
    await user.click(checkbox)

    // Close the editor
    await user.click(screen.getByRole('button', { name: 'Done' }))

    // Verify convergence badge is gone
    expect(screen.queryByText('Convergence')).not.toBeInTheDocument()

    // Save and verify the convergence gate is removed
    await user.click(screen.getByRole('button', { name: 'Save plan' }))
    await waitFor(() => expect(mocks.update).toHaveBeenCalledOnce())

    // SAFETY: mock call shape matches the update API payload with convergence gates
    const payload = mocks.update.mock.calls[0][1] as { nodes: Array<{ id: string; convergence_gate?: Array<{ node_id: string }> }> }
    const convergenceNode = payload.nodes.find((n) => n.id === 'b-1')
    expect(convergenceNode?.convergence_gate).toHaveLength(0)
  })

  it('restores the default plan name when canceling before the initial name has loaded', async () => {
    mocks.listThreads.mockReset()
    mocks.listThreads.mockImplementationOnce(() => new Promise(() => {}))

    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/continuity-plans']}>
        <Routes>
          <Route path="/continuity-plans" element={<ContinuityPlannerPage />} />
          <Route path="/continuity-plans/:id" element={<ContinuityPlannerPage />} />
        </Routes>
      </MemoryRouter>,
      { wrapper: queryWrapper },
    )

    const cancelButton = await screen.findByRole('button', { name: 'Cancel changes' })
    await user.click(cancelButton)
    expect(screen.getByLabelText('Plan name')).toHaveValue('My reading plan')
  })

  it('disables removing a non-empty lane and enables it once emptied', async () => {
    mocks.get.mockResolvedValue({
      id: 12,
      user_id: 1,
      name: 'Parallel plan',
      ordering_mode: 'informational',
      lanes: [
        { id: 'main', name: 'Reading order', order: 0 },
        { id: 'lane-2', name: 'Lane 2', order: 1 },
      ],
      nodes: [
        { id: 'issue-40', node_type: 'issue', ref_id: 40, lane_id: 'main', position: 0 , label: 'Mister Miracle #Annual 1'},
        { id: 'crossover-8', node_type: 'crossover', ref_id: 8, lane_id: 'main', position: 1 , label: 'Fourth World'},
      ],
      created_at: '2026-08-12T00:00:00Z',
      updated_at: '2026-08-12T00:00:00Z',
    })
    mocks.update.mockResolvedValue({
      id: 12,
      user_id: 1,
      name: 'Parallel plan',
      ordering_mode: 'informational',
      lanes: [{ id: 'main', name: 'Reading order', order: 0 }],
      nodes: [
        { id: 'issue-40', node_type: 'issue', ref_id: 40, lane_id: 'main', position: 0 , label: 'Mister Miracle #Annual 1'},
        { id: 'crossover-8', node_type: 'crossover', ref_id: 8, lane_id: 'main', position: 1 , label: 'Fourth World'},
      ],
      created_at: '2026-08-12T00:00:00Z',
      updated_at: '2026-08-12T00:00:00Z',
    })

    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/continuity-plans/12']}>
        <Routes>
          <Route path="/continuity-plans/:id" element={<ContinuityPlannerPage />} />
        </Routes>
      </MemoryRouter>,
      { wrapper: queryWrapper },
    )

    const removeMain = await screen.findByRole('button', { name: 'Remove lane Reading order' })
    expect(removeMain).toBeDisabled()
    const removeLane2 = screen.getByRole('button', { name: 'Remove lane Lane 2' })
    expect(removeLane2).toBeEnabled()

    // Move both steps into the second lane, then empty and remove it.
    await user.selectOptions(
      screen.getByRole('combobox', { name: /Move Mister Miracle #Annual 1 to another lane/i }),
      'lane-2',
    )
    await user.selectOptions(
      screen.getByRole('combobox', { name: /Move Fourth World to another lane/i }),
      'lane-2',
    )

    expect(screen.getByRole('button', { name: 'Remove lane Lane 2' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Remove lane Reading order' })).toBeEnabled()

    await user.click(screen.getByRole('button', { name: 'Remove lane Reading order' }))
    await user.click(screen.getByRole('button', { name: 'Save plan' }))
    await waitFor(() => expect(mocks.update).toHaveBeenCalledOnce())

    // SAFETY: mock call shape matches the update API payload with lanes
    const payload = mocks.update.mock.calls[0][1] as {
      lanes: Array<{ id: string }>
      nodes: Array<{ id: string; lane_id: string }>
    }
    expect(payload.lanes.map((lane) => lane.id)).toEqual(['lane-2'])
    expect(payload.nodes.every((node) => node.lane_id === 'lane-2')).toBe(true)
  })

})
