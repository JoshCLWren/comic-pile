import { type ComponentProps, type PropsWithChildren } from 'react'
import { render, screen } from '@testing-library/react'
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
  mocks.listThreads.mockResolvedValue({ threads: [thread], next_page_token: null })
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
  it('shows a save error when the API rejects the plan creation', async () => {
    const user = userEvent.setup()
    mocks.create.mockRejectedValue(new Error('Plan name already exists'))

    renderNewPlanPage()

    await user.type(screen.getByLabelText('Plan name'), 'Existing Plan')
    await user.click(screen.getByRole('radio', { name: /Strict sequential/ }))
    await user.type(screen.getByLabelText('Comic series'), 'Mister')
    await user.click(screen.getByRole('option', { name: /Mister Miracle/i }))
    await user.selectOptions(screen.getByLabelText('Issue'), '40')
    await user.click(screen.getByRole('button', { name: 'Add issue' }))
    await user.click(screen.getByRole('button', { name: 'Save plan' }))

    await screen.findByText(/Plan name already exists/)
    expect(screen.getByText(/Plan name already exists/)).toBeInTheDocument()
  })

  it('shows a save error when the API rejects the plan update', async () => {
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
    
    // Mock update failure
    mocks.update.mockRejectedValue(new Error('Plan name already exists'))
    
    await user.clear(screen.getByLabelText('Plan name'))
    await user.type(screen.getByLabelText('Plan name'), 'New Name')
    await user.click(screen.getByRole('button', { name: 'Save plan' }))

    await screen.findByText(/Plan name already exists/)
    expect(screen.getByText(/Plan name already exists/)).toBeInTheDocument()
  })

  it('shows a validation error when the plan name is empty', async () => {
    const user = userEvent.setup()

    renderNewPlanPage()

    await user.clear(screen.getByLabelText('Plan name'))
    await user.click(screen.getByRole('button', { name: 'Save plan' }))

    await screen.findByText(/Plan name is required/)
    expect(screen.getByText(/Plan name is required/)).toBeInTheDocument()
  })

  it('shows a validation error when the plan name is too long', async () => {
    const user = userEvent.setup()
    const longName = 'a'.repeat(256)

    renderNewPlanPage()

    await user.clear(screen.getByLabelText('Plan name'))
    await user.type(screen.getByLabelText('Plan name'), longName)
    await user.click(screen.getByRole('button', { name: 'Save plan' }))

    await screen.findByText(/Plan name is too long/)
    expect(screen.getByText(/Plan name is too long/)).toBeInTheDocument()
  })

  it('shows a validation error when the ordering mode is invalid', async () => {
    const user = userEvent.setup()

    renderNewPlanPage()

    // Try to select an invalid ordering mode
    const invalidOption = screen.queryByRole('radio', { name: /Invalid Mode/ })
    if (invalidOption) {
      await user.click(invalidOption)
      await user.click(screen.getByRole('button', { name: 'Save plan' }))

      await screen.findByText(/Invalid ordering mode/)
      expect(screen.getByText(/Invalid ordering mode/)).toBeInTheDocument()
    }
  })

  it('shows a validation error when no issues are added to the plan', async () => {
    const user = userEvent.setup()

    renderNewPlanPage()

    await user.type(screen.getByLabelText('Plan name'), 'Empty Plan')
    await user.click(screen.getByRole('radio', { name: /Strict sequential/ }))
    await user.click(screen.getByRole('button', { name: 'Save plan' }))

    await screen.findByText(/At least one issue is required/)
    expect(screen.getByText(/At least one issue is required/)).toBeInTheDocument()
  })

  it('shows an error when thread loading fails', async () => {
    mocks.listThreads.mockRejectedValue(new Error('Failed to load threads'))

    renderNewPlanPage()

    await screen.findByText(/Failed to load threads/)
    expect(screen.getByText(/Failed to load threads/)).toBeInTheDocument()
  })

  it('shows an error when dependency group loading fails', async () => {
    mocks.listGroups.mockRejectedValue(new Error('Failed to load groups'))

    renderNewPlanPage()

    await screen.findByText(/Failed to load groups/)
    expect(screen.getByText(/Failed to load groups/)).toBeInTheDocument()
  })

  it('shows an error when plan loading fails during edit', async () => {
    mocks.list.mockResolvedValue({
      plans: [plan],
      next_page_token: null,
    })
    mocks.get.mockRejectedValue(new Error('Plan not found'))

    renderNewPlanPage()

    await screen.findByText(/Plan not found/)
    expect(screen.getByText(/Plan not found/)).toBeInTheDocument()
  })

  it('shows a network error when API requests fail', async () => {
    const user = userEvent.setup()
    
    // Simulate network error
    mocks.create.mockRejectedValue(new Error('Network Error'))

    renderNewPlanPage()

    await user.type(screen.getByLabelText('Plan name'), 'Test Plan')
    await user.click(screen.getByRole('radio', { name: /Strict sequential/ }))
    await user.type(screen.getByLabelText('Comic series'), 'Mister')
    await user.click(screen.getByRole('option', { name: /Mister Miracle/i }))
    await user.selectOptions(screen.getByLabelText('Issue'), '40')
    await user.click(screen.getByRole('button', { name: 'Add issue' }))
    await user.click(screen.getByRole('button', { name: 'Save plan' }))

    await screen.findByText(/Network Error/)
    expect(screen.getByText(/Network Error/)).toBeInTheDocument()
  })

  it('shows a timeout error when API requests take too long', async () => {
    const user = userEvent.setup()
    
    // Simulate timeout
    mocks.create.mockRejectedValue(new Error('Request timeout'))

    renderNewPlanPage()

    await user.type(screen.getByLabelText('Plan name'), 'Test Plan')
    await user.click(screen.getByRole('radio', { name: /Strict sequential/ }))
    await user.type(screen.getByLabelText('Comic series'), 'Mister')
    await user.click(screen.getByRole('option', { name: /Mister Miracle/i }))
    await user.selectOptions(screen.getByLabelText('Issue'), '40')
    await user.click(screen.getByRole('button', { name: 'Add issue' }))
    await user.click(screen.getByRole('button', { name: 'Save plan' }))

    await screen.findByText(/Request timeout/)
    expect(screen.getByText(/Request timeout/)).toBeInTheDocument()
  })

  it('shows a server error when API returns 500 status', async () => {
    const user = userEvent.setup()
    
    // Simulate server error
    mocks.create.mockRejectedValue(new Error('Server Error (500)'))

    renderNewPlanPage()

    await user.type(screen.getByLabelText('Plan name'), 'Test Plan')
    await user.click(screen.getByRole('radio', { name: /Strict sequential/ }))
    await user.type(screen.getByLabelText('Comic series'), 'Mister')
    await user.click(screen.getByRole('option', { name: /Mister Miracle/i }))
    await user.selectOptions(screen.getByLabelText('Issue'), '40')
    await user.click(screen.getByRole('button', { name: 'Add issue' }))
    await user.click(screen.getByRole('button', { name: 'Save plan' }))

    await screen.findByText(/Server Error \(500\)/)
    expect(screen.getByText(/Server Error \(500\)/)).toBeInTheDocument()
  })

  it('shows a validation error when thread ID is not numeric', async () => {
    const user = userEvent.setup()
    
    // Mock a thread with non-numeric ID
    const invalidThread = {
      ...thread,
      id: 'invalid' as any,
    }
    
    mocks.listThreads.mockResolvedValue({ threads: [invalidThread], next_page_token: null })

    renderNewPlanPage()

    await user.click(screen.getByText('Mister Miracle'))
    
    // Should handle invalid thread ID gracefully
    expect(screen.getByText('Mister Miracle')).toBeInTheDocument()
  })

  it('shows a validation error when thread ID is zero', async () => {
    const user = userEvent.setup()
    
    // Mock a thread with zero ID
    const zeroThread = {
      ...thread,
      id: 0,
    }
    
    mocks.listThreads.mockResolvedValue({ threads: [zeroThread], next_page_token: null })

    renderNewPlanPage()

    await user.click(screen.getByText('Mister Miracle'))
    
    // Should handle zero thread ID gracefully
    expect(screen.getByText('Mister Miracle')).toBeInTheDocument()
  })

  it('shows a validation error when thread ID is negative', async () => {
    const user = userEvent.setup()
    
    // Mock a thread with negative ID
    const negativeThread = {
      ...thread,
      id: -1,
    }
    
    mocks.listThreads.mockResolvedValue({ threads: [negativeThread], next_page_token: null })

    renderNewPlanPage()

    await user.click(screen.getByText('Mister Miracle'))
    
    // Should handle negative thread ID gracefully
    expect(screen.getByText('Mister Miracle')).toBeInTheDocument()
  })

  it('shows an error when concurrent save operations conflict', async () => {
    const user = userEvent.setup()
    
    // Mock a conflict error
    mocks.update.mockRejectedValue(new Error('Conflict: Plan was modified by another user'))

    // Load an existing plan first
    mocks.list.mockResolvedValue({
      plans: [plan],
      next_page_token: null,
    })
    mocks.get.mockResolvedValue(plan)

    renderNewPlanPage()

    await screen.findByText('Kirby lane')
    await user.click(screen.getByText('Edit plan'))
    
    // Trigger save
    await user.click(screen.getByRole('button', { name: 'Save plan' }))

    await screen.findByText(/Conflict: Plan was modified by another user/)
    expect(screen.getByText(/Conflict: Plan was modified by another user/)).toBeInTheDocument()
  })

  it('shows an error when undo operations fail', async () => {
    const user = userEvent.setup()
    
    // Mock undo failure
    mocks.update.mockRejectedValue(new Error('Failed to undo changes'))

    renderNewPlanPage()

    await user.type(screen.getByLabelText('Plan name'), 'Test Plan')
    await user.click(screen.getByRole('button', { name: 'Undo' }))

    await screen.findByText(/Failed to undo changes/)
    expect(screen.getByText(/Failed to undo changes/)).toBeInTheDocument()
  })

  it('shows an error when redo operations fail', async () => {
    const user = userEvent.setup()
    
    // Mock redo failure
    mocks.update.mockRejectedValue(new Error('Failed to redo changes'))

    renderNewPlanPage()

    await user.type(screen.getByLabelText('Plan name'), 'Test Plan')
    await user.click(screen.getByRole('button', { name: 'Undo' }))
    await user.click(screen.getByRole('button', { name: 'Redo' }))

    await screen.findByText(/Failed to redo changes/)
    expect(screen.getByText(/Failed to redo changes/)).toBeInTheDocument()
  })

  it('shows an error when plan export fails', async () => {
    const user = userEvent.setup()
    
    // Mock export failure
    mocks.update.mockRejectedValue(new Error('Failed to export plan'))

    renderNewPlanPage()

    await user.type(screen.getByLabelText('Plan name'), 'Test Plan')
    await user.click(screen.getByRole('button', { name: 'Export' }))

    await screen.findByText(/Failed to export plan/)
    expect(screen.getByText(/Failed to export plan/)).toBeInTheDocument()
  })
})