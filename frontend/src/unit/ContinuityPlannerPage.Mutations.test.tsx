import { type ComponentProps, type PropsWithChildren } from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { continuityPlansApi } from '../services/api-continuity-plans'
import { dependencyGroupsApi } from '../services/api-dependency-groups'
import { issuesApi } from '../services/api-issues'
import { threadsApi } from '../services/api'
import ContinuityPlannerPageImpl from '../pages/ContinuityPlannerPage'

interface AddMaterialProbeProps {
  commitDisabled?: boolean
  onCommitPendingChange?: (isPending: boolean) => void
}

const addMaterialProbe = {
  current: null as AddMaterialProbeProps | null,
}

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

const plan = {
  id: 12,
  user_id: 1,
  name: 'Kirby lane',
  ordering_mode: 'strict_sequential',
  lanes: [{ id: 'main', name: 'Reading order', order: 0 }],
  nodes: [],
  created_at: '2026-08-12T00:00:00Z',
  updated_at: '2026-08-12T00:00:00Z',
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
  mocks.listIssues.mockResolvedValue({ issues: [issue], total_count: 1, page_size: 100, next_page_token: null })
  mocks.getIssue.mockResolvedValue(issue)
  mocks.listThreads.mockResolvedValue({ threads: [thread, secondThread], next_page_token: null })
  mocks.getThread.mockResolvedValue(thread)
  mocks.create.mockResolvedValue(plan)
  mocks.update.mockResolvedValue(plan)
})

afterEach(() => {
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
    renderNewPlanPage()

    await user.clear(screen.getByLabelText('Plan name'))
    await user.type(screen.getByLabelText('Plan name'), 'Kirby lane')
    await user.click(screen.getByRole('radio', { name: /Strict sequential/ }))
    await user.type(screen.getByLabelText('Comic series'), 'Mister')
    await user.click(screen.getByRole('option', { name: /Mister Miracle/i }))
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
        expect.objectContaining({ node_type: 'dependency_group', ref_id: 8, position: 1 }),
      ],
    }))
  })

  it('creates a parallel plan from shared human-facing selectors', async () => {
    const user = userEvent.setup()
    renderNewPlanPage()

    await user.clear(screen.getByLabelText('Plan name'))
    await user.type(screen.getByLabelText('Plan name'), 'Fourth World')
    await user.click(screen.getByRole('radio', { name: /Parallel/ }))
    await user.type(screen.getByLabelText('Comic series'), 'Mister')
    await user.click(screen.getByRole('option', { name: /Mister Miracle/i }))
    await user.selectOptions(screen.getByLabelText('Issue'), '40')
    await user.click(screen.getByRole('button', { name: 'Add issue' }))
    await user.selectOptions(screen.getByLabelText('Crossover'), '8')
    await user.click(screen.getByRole('button', { name: 'Add crossover' }))
    await user.click(screen.getByRole('button', { name: 'Save plan' }))

    await waitFor(() => expect(mocks.create).toHaveBeenCalledOnce())
    expect(mocks.create).toHaveBeenCalledWith(expect.objectContaining({
      name: 'Fourth World',
      ordering_mode: 'parallel',
      nodes: [
        expect.objectContaining({ node_type: 'issue', ref_id: 40, position: 0 }),
        expect.objectContaining({ node_type: 'dependency_group', ref_id: 8, position: 0 }),
      ],
    }))
  })

  it('creates a checkpoint plan from shared human-facing selectors', async () => {
    const user = userEvent.setup()
    renderNewPlanPage()

    await user.clear(screen.getByLabelText('Plan name'))
    await user.type(screen.getByLabelText('Plan name'), 'Checkpoint Plan')
    await user.click(screen.getByRole('radio', { name: /Checkpoint/ }))
    await user.type(screen.getByLabelText('Comic series'), 'Mister')
    await user.click(screen.getByRole('option', { name: /Mister Miracle/i }))
    await user.selectOptions(screen.getByLabelText('Issue'), '40')
    await user.click(screen.getByRole('button', { name: 'Add issue' }))
    await user.click(screen.getByRole('button', { name: 'Save plan' }))

    await waitFor(() => expect(mocks.create).toHaveBeenCalledOnce())
    expect(mocks.create).toHaveBeenCalledWith(expect.objectContaining({
      name: 'Checkpoint Plan',
      ordering_mode: 'checkpoint',
      nodes: [
        expect.objectContaining({ node_type: 'issue', ref_id: 40, position: 0 }),
      ],
    }))
  })

  it('updates an existing plan with new nodes', async () => {
    const user = userEvent.setup()
    
    // Load an existing plan first
    mocks.list.mockResolvedValue({
      plans: [plan],
      next_page_token: null,
    })
    mocks.get.mockResolvedValue(plan)

    renderNewPlanPage()

    await screen.findByText('Kirby lane')
    await user.click(screen.getByText('Edit plan'))
    
    // Add a new issue
    await user.type(screen.getByLabelText('Comic series'), 'New')
    await user.click(screen.getByRole('option', { name: /New Gods/i }))
    await user.selectOptions(screen.getByLabelText('Issue'), '41')
    await user.click(screen.getByRole('button', { name: 'Add issue' }))
    await user.click(screen.getByRole('button', { name: 'Save plan' }))

    await waitFor(() => expect(mocks.update).toHaveBeenCalledOnce())
    expect(mocks.update).toHaveBeenCalledWith(expect.objectContaining({
      id: 12,
      name: 'Kirby lane',
      ordering_mode: 'strict_sequential',
      nodes: [
        expect.objectContaining({ node_type: 'issue', ref_id: 40, position: 0 }),
        expect.objectContaining({ node_type: 'issue', ref_id: 41, position: 1 }),
      ],
    }))
  })

  it('removes a node from an existing plan', async () => {
    const user = userEvent.setup()
    
    // Load a plan with multiple nodes
    const planWithNodes = {
      ...plan,
      nodes: [
        { id: 1, node_type: 'issue', ref_id: 40, position: 0 },
        { id: 2, node_type: 'dependency_group', ref_id: 8, position: 1 },
      ],
    }
    
    mocks.list.mockResolvedValue({
      plans: [planWithNodes],
      next_page_token: null,
    })
    mocks.get.mockResolvedValue(planWithNodes)

    renderNewPlanPage()

    await screen.findByText('Kirby lane')
    await user.click(screen.getByText('Edit plan'))
    
    // Remove a node
    await user.click(screen.getByRole('button', { name: 'Remove issue' }))
    await user.click(screen.getByRole('button', { name: 'Save plan' }))

    await waitFor(() => expect(mocks.update).toHaveBeenCalledOnce())
    expect(mocks.update).toHaveBeenCalledWith(expect.objectContaining({
      id: 12,
      name: 'Kirby lane',
      ordering_mode: 'strict_sequential',
      nodes: [
        expect.objectContaining({ node_type: 'dependency_group', ref_id: 8, position: 0 }),
      ],
    }))
  })

  it('reorders nodes in a sequential plan', async () => {
    const user = userEvent.setup()
    
    // Load a plan with multiple nodes
    const planWithNodes = {
      ...plan,
      nodes: [
        { id: 1, node_type: 'issue', ref_id: 40, position: 0 },
        { id: 2, node_type: 'dependency_group', ref_id: 8, position: 1 },
      ],
    }
    
    mocks.list.mockResolvedValue({
      plans: [planWithNodes],
      next_page_token: null,
    })
    mocks.get.mockResolvedValue(planWithNodes)

    renderNewPlanPage()

    await screen.findByText('Kirby lane')
    await user.click(screen.getByText('Edit plan'))
    
    // Reorder nodes
    await user.click(screen.getByRole('button', { name: 'Move up' }))
    await user.click(screen.getByRole('button', { name: 'Save plan' }))

    await waitFor(() => expect(mocks.update).toHaveBeenCalledOnce())
    expect(mocks.update).toHaveBeenCalledWith(expect.objectContaining({
      id: 12,
      name: 'Kirby lane',
      ordering_mode: 'strict_sequential',
      nodes: [
        expect.objectContaining({ node_type: 'dependency_group', ref_id: 8, position: 0 }),
        expect.objectContaining({ node_type: 'issue', ref_id: 40, position: 1 }),
      ],
    }))
  })

  it('adds a lane to a plan', async () => {
    const user = userEvent.setup()
    
    renderNewPlanPage()

    await user.clear(screen.getByLabelText('Plan name'))
    await user.type(screen.getByLabelText('Plan name'), 'Multi-lane Plan')
    await user.click(screen.getByRole('radio', { name: /Strict sequential/ }))
    await user.click(screen.getByRole('button', { name: 'Add lane' }))
    await user.type(screen.getByLabelText('Lane name'), 'Side stories')
    await user.click(screen.getByRole('button', { name: 'Save plan' }))

    await waitFor(() => expect(mocks.create).toHaveBeenCalledOnce())
    expect(mocks.create).toHaveBeenCalledWith(expect.objectContaining({
      name: 'Multi-lane Plan',
      ordering_mode: 'strict_sequential',
      lanes: [
        { id: 'main', name: 'Reading order', order: 0 },
        { id: 'side-stories', name: 'Side stories', order: 1 },
      ],
      nodes: [],
    }))
  })

  it('removes a lane from a plan', async () => {
    const user = userEvent.setup()
    
    // Load a plan with multiple lanes
    const multiLanePlan = {
      ...plan,
      lanes: [
        { id: 'main', name: 'Reading order', order: 0 },
        { id: 'side-stories', name: 'Side stories', order: 1 },
      ],
    }
    
    mocks.list.mockResolvedValue({
      plans: [multiLanePlan],
      next_page_token: null,
    })
    mocks.get.mockResolvedValue(multiLanePlan)

    renderNewPlanPage()

    await screen.findByText('Kirby lane')
    await user.click(screen.getByText('Edit plan'))
    
    // Remove a lane
    await user.click(screen.getByRole('button', { name: 'Remove lane' }))
    await user.click(screen.getByRole('button', { name: 'Save plan' }))

    await waitFor(() => expect(mocks.update).toHaveBeenCalledOnce())
    expect(mocks.update).toHaveBeenCalledWith(expect.objectContaining({
      id: 12,
      name: 'Kirby lane',
      ordering_mode: 'strict_sequential',
      lanes: [
        { id: 'main', name: 'Reading order', order: 0 },
      ],
      nodes: [],
    }))
  })

  it('renames a lane in a plan', async () => {
    const user = userEvent.setup()
    
    // Load a plan with multiple lanes
    const multiLanePlan = {
      ...plan,
      lanes: [
        { id: 'main', name: 'Reading order', order: 0 },
        { id: 'side-stories', name: 'Side stories', order: 1 },
      ],
    }
    
    mocks.list.mockResolvedValue({
      plans: [multiLanePlan],
      next_page_token: null,
    })
    mocks.get.mockResolvedValue(multiLanePlan)

    renderNewPlanPage()

    await screen.findByText('Kirby lane')
    await user.click(screen.getByText('Edit plan'))
    
    // Rename a lane
    await user.clear(screen.getByLabelText('Lane name'))
    await user.type(screen.getByLabelText('Lane name'), 'Main stories')
    await user.click(screen.getByRole('button', { name: 'Save plan' }))

    await waitFor(() => expect(mocks.update).toHaveBeenCalledOnce())
    expect(mocks.update).toHaveBeenCalledWith(expect.objectContaining({
      id: 12,
      name: 'Kirby lane',
      ordering_mode: 'strict_sequential',
      lanes: [
        { id: 'main', name: 'Main stories', order: 0 },
        { id: 'side-stories', name: 'Side stories', order: 1 },
      ],
      nodes: [],
    }))
  })

  it('adds a checkpoint to a checkpoint plan', async () => {
    const user = userEvent.setup()
    
    // Load a checkpoint plan
    const checkpointPlan = {
      ...plan,
      ordering_mode: 'checkpoint',
      nodes: [
        { id: 1, node_type: 'issue', ref_id: 40, position: 0 },
      ],
    }
    
    mocks.list.mockResolvedValue({
      plans: [checkpointPlan],
      next_page_token: null,
    })
    mocks.get.mockResolvedValue(checkpointPlan)

    renderNewPlanPage()

    await screen.findByText('Kirby lane')
    await user.click(screen.getByText('Edit plan'))
    
    // Add a checkpoint
    await user.click(screen.getByRole('button', { name: 'Add checkpoint' }))
    await user.click(screen.getByRole('button', { name: 'Save plan' }))

    await waitFor(() => expect(mocks.update).toHaveBeenCalledOnce())
    expect(mocks.update).toHaveBeenCalledWith(expect.objectContaining({
      id: 12,
      name: 'Kirby lane',
      ordering_mode: 'checkpoint',
      nodes: [
        expect.objectContaining({ node_type: 'issue', ref_id: 40, position: 0 }),
        expect.objectContaining({ node_type: 'checkpoint', position: 1 }),
      ],
    }))
  })

  it('converges parallel nodes when convergence is enabled', async () => {
    const user = userEvent.setup()
    
    // Load a parallel plan
    const parallelPlan = {
      ...plan,
      ordering_mode: 'parallel',
      nodes: [
        { id: 1, node_type: 'issue', ref_id: 40, position: 0 },
        { id: 2, node_type: 'dependency_group', ref_id: 8, position: 0 },
      ],
    }
    
    mocks.list.mockResolvedValue({
      plans: [parallelPlan],
      next_page_token: null,
    })
    mocks.get.mockResolvedValue(parallelPlan)

    renderNewPlanPage()

    await screen.findByText('Kirby lane')
    await user.click(screen.getByText('Edit plan'))
    
    // Enable convergence
    await user.click(screen.getByRole('checkbox', { name: /Enable convergence/ }))
    await user.click(screen.getByRole('button', { name: 'Save plan' }))

    await waitFor(() => expect(mocks.update).toHaveBeenCalledOnce())
    expect(mocks.update).toHaveBeenCalledWith(expect.objectContaining({
      id: 12,
      name: 'Kirby lane',
      ordering_mode: 'parallel',
      nodes: [
        expect.objectContaining({ node_type: 'issue', ref_id: 40, position: 0 }),
        expect.objectContaining({ node_type: 'dependency_group', ref_id: 8, position: 0 }),
      ],
      converge_parallel_nodes: true,
    }))
  })

  it('exports a plan to JSON', async () => {
    const user = userEvent.setup()
    
    // Load an existing plan
    mocks.list.mockResolvedValue({
      plans: [plan],
      next_page_token: null,
    })
    mocks.get.mockResolvedValue(plan)

    renderNewPlanPage()

    await screen.findByText('Kirby lane')
    await user.click(screen.getByText('Edit plan'))
    
    // Export plan
    await user.click(screen.getByRole('button', { name: 'Export' }))

    // Should trigger download or show export dialog
    expect(screen.getByText(/Export plan/)).toBeInTheDocument()
  })

  it('imports a plan from JSON', async () => {
    const user = userEvent.setup()
    
    // Mock file import
    const fileContent = JSON.stringify({
      name: 'Imported Plan',
      ordering_mode: 'strict_sequential',
      nodes: [],
    })
    
    const file = new File([fileContent], 'plan.json', { type: 'application/json' })
    
    renderNewPlanPage()

    // Import plan
    const fileInput = screen.getByLabelText('Import plan')
    await user.upload(fileInput, file)
    await user.click(screen.getByRole('button', { name: 'Import' }))

    await waitFor(() => expect(mocks.create).toHaveBeenCalledOnce())
    expect(mocks.create).toHaveBeenCalledWith(expect.objectContaining({
      name: 'Imported Plan',
      ordering_mode: 'strict_sequential',
      nodes: [],
    }))
  })

  it('clones an existing plan', async () => {
    const user = userEvent.setup()
    
    // Load an existing plan
    mocks.list.mockResolvedValue({
      plans: [plan],
      next_page_token: null,
    })
    mocks.get.mockResolvedValue(plan)

    renderNewPlanPage()

    await screen.findByText('Kirby lane')
    await user.click(screen.getByText('Edit plan'))
    
    // Clone plan
    await user.click(screen.getByRole('button', { name: 'Clone' }))

    await waitFor(() => expect(mocks.create).toHaveBeenCalledOnce())
    expect(mocks.create).toHaveBeenCalledWith(expect.objectContaining({
      name: 'Kirby lane (Copy)',
      ordering_mode: 'strict_sequential',
      nodes: [],
    }))
  })

  it('duplicates a node in a plan', async () => {
    const user = userEvent.setup()
    
    // Load a plan with nodes
    const planWithNodes = {
      ...plan,
      nodes: [
        { id: 1, node_type: 'issue', ref_id: 40, position: 0 },
      ],
    }
    
    mocks.list.mockResolvedValue({
      plans: [planWithNodes],
      next_page_token: null,
    })
    mocks.get.mockResolvedValue(planWithNodes)

    renderNewPlanPage()

    await screen.findByText('Kirby lane')
    await user.click(screen.getByText('Edit plan'))
    
    // Duplicate node
    await user.click(screen.getByRole('button', { name: 'Duplicate issue' }))
    await user.click(screen.getByRole('button', { name: 'Save plan' }))

    await waitFor(() => expect(mocks.update).toHaveBeenCalledOnce())
    expect(mocks.update).toHaveBeenCalledWith(expect.objectContaining({
      id: 12,
      name: 'Kirby lane',
      ordering_mode: 'strict_sequential',
      nodes: [
        expect.objectContaining({ node_type: 'issue', ref_id: 40, position: 0 }),
        expect.objectContaining({ node_type: 'issue', ref_id: 40, position: 1 }),
      ],
    }))
  })
})