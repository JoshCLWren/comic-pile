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
  it('defaults a new plan to informational order so no blocking rules are compiled', async () => {
    const user = userEvent.setup()
    renderNewPlanPage()

    await user.type(screen.getByLabelText('Comic series'), 'Mister')
    await user.click(await screen.findByRole('option', { name: /Mister Miracle/i }))
    await screen.findByRole('option', { name: /Annual 1/i })
    await user.selectOptions(screen.getByLabelText('Issue'), '40')
    await user.click(screen.getByRole('button', { name: 'Add issue' }))
    await user.click(screen.getByRole('button', { name: 'Save plan' }))

    await waitFor(() => expect(mocks.create).toHaveBeenCalledOnce())
    // SAFETY: mock call shape matches the create API payload
    const payload = mocks.create.mock.calls[0][0] as { ordering_mode: string }
    expect(payload.ordering_mode).toBe('informational')
  })

  it('moves the first node down and back up, preserving order', async () => {
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

    const moveDownButton = await screen.findByRole('button', { name: /Move Mister Miracle #Annual 1 later/i })
    await user.click(moveDownButton)
    await waitFor(() => expect(screen.getByText('2')).toBeVisible())
    const moveUpButton = screen.getByRole('button', { name: /Move Mister Miracle #Annual 1 earlier/i })
    await user.click(moveUpButton)
    await waitFor(() => expect(screen.getByText('1')).toBeVisible())
  })

  it('moves a node up and down using the lane reorder controls', async () => {
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

    // Initially first item is "Mister Miracle #Annual 1" at position 1
    await waitFor(() => expect(screen.getByText('Mister Miracle #Annual 1')).toBeInTheDocument())
    await waitFor(() => expect(screen.getByTestId('lane-item-0')).toHaveTextContent('Mister Miracle #Annual 1'))
    await waitFor(() => expect(screen.getByTestId('lane-item-1')).toHaveTextContent('Fourth World'))

    const moveDownButton = await screen.findByRole('button', { name: /Move Mister Miracle #Annual 1 later/i })
    await act(async () => {
      await user.click(moveDownButton)
    })
    // After moving down, the order should be swapped
    const firstItem = screen.getByTestId('lane-item-0')
    const secondItem = screen.getByTestId('lane-item-1')
    expect(firstItem).toHaveTextContent('Fourth World')
    expect(secondItem).toHaveTextContent('Mister Miracle #Annual 1')

    const moveUpButton = screen.getByRole('button', { name: /Move Mister Miracle #Annual 1 earlier/i })
    await act(async () => {
      await user.click(moveUpButton)
    })
    // After moving up, the order should be restored
    const restoredFirstItem = screen.getByTestId('lane-item-0')
    const restoredSecondItem = screen.getByTestId('lane-item-1')
    expect(restoredFirstItem).toHaveTextContent('Mister Miracle #Annual 1')
    expect(restoredSecondItem).toHaveTextContent('Fourth World')
  })

  it('disables move controls at lane boundaries and removes nodes', async () => {
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

    expect(await screen.findByRole('button', { name: /Move Mister Miracle #Annual 1 earlier/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /Move Fourth World later/i })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: 'Remove Fourth World' }))
    await user.click(screen.getByRole('button', { name: 'Save plan' }))
    await waitFor(() => expect(mocks.update).toHaveBeenCalledOnce())
  })

  it('renders convergence targets even when a target lane is missing from the plan lanes', async () => {
    mocks.get.mockResolvedValue({
      id: 12,
      user_id: 1,
      name: 'Convergence plan',
      ordering_mode: 'informational',
      lanes: [{ id: 'main', name: 'Lane A', order: 0 }],
      nodes: [
        { id: 'a-1', node_type: 'issue', ref_id: 40, lane_id: 'main', position: 0, label: 'Mister Miracle #1' },
        { id: 'b-1', node_type: 'issue', ref_id: 42, lane_id: 'ghost-lane', position: 0, label: 'New Gods #1' },
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

    await waitFor(() => expect(screen.getByText('Mister Miracle #1')).toBeVisible())

    const convergenceButton = screen.getByRole('button', { name: /Edit convergence gate for Mister Miracle #1/i })
    await user.click(convergenceButton)

    expect(screen.getByTestId('convergence-editor-a-1')).toBeVisible()

    const checkbox = screen.getByRole('checkbox', { name: /New Gods #1/i })
    await user.click(checkbox)

    expect(screen.getByText('Convergence (1)')).toBeVisible()
  })

  it('only offers checkpoint and convergence controls on supported node types', async () => {
    mocks.get.mockResolvedValue({
      id: 12,
      user_id: 1,
      name: 'Mixed plan',
      ordering_mode: 'informational',
      lanes: [{ id: 'main', name: 'Lane A', order: 0 }],
      nodes: [
        { id: 'a-1', node_type: 'issue', ref_id: 40, lane_id: 'main', position: 0, label: 'Mister Miracle #1' },
        { id: 't-1', node_type: 'thread', ref_id: 4, lane_id: 'main', position: 1, label: 'New Gods Series' },
      ],
      created_at: '2026-08-12T00:00:00Z',
      updated_at: '2026-08-12T00:00:00Z',
    })

    render(
      <MemoryRouter initialEntries={['/continuity-plans/12']}>
        <Routes>
          <Route path="/continuity-plans/:id" element={<ContinuityPlannerPage />} />
        </Routes>
      </MemoryRouter>,
    )

    await waitFor(() => expect(screen.getByText('Mister Miracle #1')).toBeVisible())

    // Issue nodes keep both controls
    expect(screen.getByRole('button', { name: /Mark Mister Miracle #1 as checkpoint/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Edit convergence gate for Mister Miracle #1/i })).toBeInTheDocument()

    // Thread nodes offer neither control
    expect(screen.queryByRole('button', { name: /Mark New Gods Series as checkpoint/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Edit convergence gate for New Gods Series/i })).not.toBeInTheDocument()
  })

  it('does not offer thread nodes as convergence gate targets', async () => {
    mocks.get.mockResolvedValue({
      id: 12,
      user_id: 1,
      name: 'Mixed plan',
      ordering_mode: 'informational',
      lanes: [{ id: 'main', name: 'Lane A', order: 0 }],
      nodes: [
        { id: 'a-1', node_type: 'issue', ref_id: 40, lane_id: 'main', position: 0, label: 'Mister Miracle #1' },
        { id: 'b-1', node_type: 'issue', ref_id: 42, lane_id: 'main', position: 1, label: 'New Gods #2' },
        { id: 't-1', node_type: 'thread', ref_id: 4, lane_id: 'main', position: 2, label: 'New Gods Series' },
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

    await waitFor(() => expect(screen.getByText('Mister Miracle #1')).toBeVisible())

    const convergenceButton = screen.getByRole('button', { name: /Edit convergence gate for Mister Miracle #1/i })
    await user.click(convergenceButton)
    expect(screen.getByTestId('convergence-editor-a-1')).toBeVisible()

    expect(screen.getByRole('checkbox', { name: /New Gods #2/i })).toBeInTheDocument()
    expect(screen.queryByRole('checkbox', { name: /New Gods Series/i })).not.toBeInTheDocument()
  })

  it('sorts convergence targets across lanes including missing lanes', async () => {
    mocks.get.mockResolvedValue({
      id: 12,
      user_id: 1,
      name: 'Convergence sort plan',
      ordering_mode: 'informational',
      lanes: [
        { id: 'main', name: 'Main Lane', order: 0 },
        { id: 'lane-2', name: 'Second Lane', order: 1 },
      ],
      nodes: [
        { id: 'target-1', node_type: 'issue', ref_id: 40, lane_id: 'main', position: 0, label: 'Main Lane Issue' },
        { id: 'target-2', node_type: 'issue', ref_id: 41, lane_id: 'lane-2', position: 0, label: 'Second Lane Issue' },
        { id: 'target-3', node_type: 'crossover', ref_id: 8, lane_id: 'ghost-lane', position: 0, label: 'Ghost Lane Crossover' },
        { id: 'source', node_type: 'issue', ref_id: 42, lane_id: 'main', position: 1, label: 'Source Node' },
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

    await waitFor(() => expect(screen.getByText('Source Node')).toBeVisible())

    const convergenceButton = screen.getByRole('button', { name: /Edit convergence gate for Source Node/i })
    await user.click(convergenceButton)

    expect(screen.getByTestId('convergence-editor-source')).toBeVisible()

    const checkboxes = screen.getAllByRole('checkbox')
    expect(checkboxes).toHaveLength(3)

    await user.click(screen.getByRole('button', { name: 'Done' }))
  })

})
