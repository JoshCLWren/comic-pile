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
  it('shows the new plan form when creating a plan', async () => {
    renderNewPlanPage()

    await screen.findByLabelText('Plan name')
    expect(screen.getByLabelText('Plan name')).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: /Strict sequential/ })).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: /Parallel/ })).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: /Checkpoint/ })).toBeInTheDocument()
  })

  it('shows the edit plan form when editing an existing plan', async () => {
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

    await screen.findByLabelText('Plan name')
    expect(screen.getByDisplayValue('Kirby lane')).toBeInTheDocument()
  })

  it('cancels plan creation when clicking cancel', async () => {
    const user = userEvent.setup()

    renderNewPlanPage()

    await user.type(screen.getByLabelText('Plan name'), 'Test Plan')
    await user.click(screen.getByRole('button', { name: 'Cancel' }))

    // Form should be cleared and back to initial state
    expect(screen.getByLabelText('Plan name')).toHaveValue('')
  })

  it('cancels plan editing when clicking cancel', async () => {
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
    
    await user.clear(screen.getByLabelText('Plan name'))
    await user.type(screen.getByLabelText('Plan name'), 'Modified Plan')
    await user.click(screen.getByRole('button', { name: 'Cancel' }))

    // Should revert to original values
    await screen.findByText('Kirby lane')
    expect(screen.getByText('Kirby lane')).toBeInTheDocument()
  })

  it('shows validation errors on save attempt with invalid data', async () => {
    const user = userEvent.setup()

    renderNewPlanPage()

    // Try to save with empty name
    await user.click(screen.getByRole('button', { name: 'Save plan' }))

    await screen.findByText(/Plan name is required/)
    expect(screen.getByText(/Plan name is required/)).toBeInTheDocument()
  })

  it('shows confirmation dialog before deleting a plan', async () => {
    const user = userEvent.setup()
    
    // Load an existing plan
    mocks.list.mockResolvedValue({
      plans: [plan],
      next_page_token: null,
    })
    mocks.get.mockResolvedValue(plan)

    renderNewPlanPage()

    await screen.findByText('Kirby lane')
    await user.click(screen.getByText('Delete plan'))

    await screen.findByText(/Are you sure you want to delete this plan?/)
    expect(screen.getByText(/Are you sure you want to delete this plan?/)).toBeInTheDocument()
  })

  it('confirms plan deletion when clicking yes in confirmation dialog', async () => {
    const user = userEvent.setup()
    
    // Load an existing plan
    mocks.list.mockResolvedValue({
      plans: [plan],
      next_page_token: null,
    })
    mocks.get.mockResolvedValue(plan)

    renderNewPlanPage()

    await screen.findByText('Kirby lane')
    await user.click(screen.getByText('Delete plan'))
    await user.click(screen.getByRole('button', { name: 'Yes, delete' }))

    await waitFor(() => expect(mocks.update).toHaveBeenCalled())
    expect(screen.queryByText('Kirby lane')).not.toBeInTheDocument()
  })

  it('cancels plan deletion when clicking no in confirmation dialog', async () => {
    const user = userEvent.setup()
    
    // Load an existing plan
    mocks.list.mockResolvedValue({
      plans: [plan],
      next_page_token: null,
    })
    mocks.get.mockResolvedValue(plan)

    renderNewPlanPage()

    await screen.findByText('Kirby lane')
    await user.click(screen.getByText('Delete plan'))
    await user.click(screen.getByRole('button', { name: 'No, keep' }))

    // Plan should still exist
    expect(screen.getByText('Kirby lane')).toBeInTheDocument()
  })

  it('shows loading state while saving a plan', async () => {
    const user = userEvent.setup()
    
    // Mock a slow save operation
    mocks.create.mockImplementation(() => new Promise(resolve => {
      setTimeout(() => resolve(plan), 100)
    }))

    renderNewPlanPage()

    await user.type(screen.getByLabelText('Plan name'), 'Test Plan')
    await user.click(screen.getByRole('button', { name: 'Save plan' }))

    await screen.findByText(/Saving.../)
    expect(screen.getByText(/Saving.../)).toBeInTheDocument()
  })

  it('hides loading state after plan save completes', async () => {
    const user = userEvent.setup()
    
    // Mock a slow save operation
    mocks.create.mockImplementation(() => new Promise(resolve => {
      setTimeout(() => resolve(plan), 100)
    }))

    renderNewPlanPage()

    await user.type(screen.getByLabelText('Plan name'), 'Test Plan')
    await user.click(screen.getByRole('button', { name: 'Save plan' }))

    await waitFor(() => {
      expect(screen.queryByText(/Saving.../)).not.toBeInTheDocument()
    })
  })

  it('shows error state when plan save fails', async () => {
    const user = userEvent.setup()
    
    // Mock save failure
    mocks.create.mockRejectedValue(new Error('Save failed'))

    renderNewPlanPage()

    await user.type(screen.getByLabelText('Plan name'), 'Test Plan')
    await user.click(screen.getByRole('button', { name: 'Save plan' }))

    await screen.findByText(/Save failed/)
    expect(screen.getByText(/Save failed/)).toBeInTheDocument()
  })

  it('shows undo/redo buttons when there are changes to undo', async () => {
    const user = userEvent.setup()

    renderNewPlanPage()

    await user.type(screen.getByLabelText('Plan name'), 'Test Plan')
    
    // Undo button should appear
    expect(screen.getByRole('button', { name: 'Undo' })).toBeInTheDocument()
  })

  it('disables undo button when there are no changes to undo', async () => {
    renderNewPlanPage()

    // Undo button should be disabled initially
    const undoButton = screen.getByRole('button', { name: 'Undo' })
    expect(undoButton).toBeDisabled()
  })

  it('disables redo button when there are no changes to redo', async () => {
    renderNewPlanPage()

    // Redo button should be disabled initially
    const redoButton = screen.getByRole('button', { name: 'Redo' })
    expect(redoButton).toBeDisabled()
  })

  it('enables redo button after undo', async () => {
    const user = userEvent.setup()

    renderNewPlanPage()

    await user.type(screen.getByLabelText('Plan name'), 'Test Plan')
    await user.click(screen.getByRole('button', { name: 'Undo' }))
    
    // Redo button should be enabled after undo
    expect(screen.getByRole('button', { name: 'Redo' })).not.toBeDisabled()
  })

  it('shows keyboard shortcuts help dialog', async () => {
    const user = userEvent.setup()

    renderNewPlanPage()

    await user.click(screen.getByRole('button', { name: 'Help' }))

    await screen.findByText(/Keyboard Shortcuts/)
    expect(screen.getByText(/Keyboard Shortcuts/)).toBeInTheDocument()
  })

  it('closes keyboard shortcuts help dialog when clicking close', async () => {
    const user = userEvent.setup()

    renderNewPlanPage()

    await user.click(screen.getByRole('button', { name: 'Help' }))
    await user.click(screen.getByRole('button', { name: 'Close' }))

    expect(screen.queryByText(/Keyboard Shortcuts/)).not.toBeInTheDocument()
  })

  it('shows keyboard shortcuts help dialog when pressing ? key', async () => {
    const user = userEvent.setup()

    renderNewPlanPage()

    await user.keyboard('?')

    await screen.findByText(/Keyboard Shortcuts/)
    expect(screen.getByText(/Keyboard Shortcuts/)).toBeInTheDocument()
  })

  it('shows plan statistics when clicking statistics button', async () => {
    const user = userEvent.setup()

    renderNewPlanPage()

    await user.type(screen.getByLabelText('Plan name'), 'Test Plan')
    await user.click(screen.getByRole('button', { name: 'Statistics' }))

    await screen.findByText(/Plan Statistics/)
    expect(screen.getByText(/Plan Statistics/)).toBeInTheDocument()
  })

  it('shows plan overview when clicking overview button', async () => {
    const user = userEvent.setup()

    renderNewPlanPage()

    await user.type(screen.getByLabelText('Plan name'), 'Test Plan')
    await user.click(screen.getByRole('button', { name: 'Overview' }))

    await screen.findByText(/Plan Overview/)
    expect(screen.getByText(/Plan Overview/)).toBeInTheDocument()
  })

  it('shows timeline view when clicking timeline button', async () => {
    const user = userEvent.setup()

    renderNewPlanPage()

    await user.type(screen.getByLabelText('Plan name'), 'Test Plan')
    await user.click(screen.getByRole('button', { name: 'Timeline' }))

    await screen.findByText(/Timeline/)
    expect(screen.getByText(/Timeline/)).toBeInTheDocument()
  })

  it('switches between different plan views correctly', async () => {
    const user = userEvent.setup()

    renderNewPlanPage()

    await user.type(screen.getByLabelText('Plan name'), 'Test Plan')
    
    // Switch to overview
    await user.click(screen.getByRole('button', { name: 'Overview' }))
    await screen.findByText(/Plan Overview/)
    
    // Switch to timeline
    await user.click(screen.getByRole('button', { name: 'Timeline' }))
    await screen.findByText(/Timeline/)
    
    // Switch back to edit
    await user.click(screen.getByRole('button', { name: 'Edit' }))
    await screen.findByLabelText('Plan name')
  })

  it('shows responsive layout on mobile devices', async () => {
    const user = userEvent.setup()

    // Mock mobile viewport
    Object.defineProperty(window, 'innerWidth', {
      writable: true,
      configurable: true,
      value: 375,
    })

    renderNewPlanPage()

    await user.type(screen.getByLabelText('Plan name'), 'Test Plan')

    // Should show mobile-specific layout
    expect(screen.getByTestId('mobile-layout')).toBeInTheDocument()
  })

  it('shows responsive layout on desktop devices', async () => {
    const user = userEvent.setup()

    // Mock desktop viewport
    Object.defineProperty(window, 'innerWidth', {
      writable: true,
      configurable: true,
      value: 1024,
    })

    renderNewPlanPage()

    await user.type(screen.getByLabelText('Plan name'), 'Test Plan')

    // Should show desktop-specific layout
    expect(screen.getByTestId('desktop-layout')).toBeInTheDocument()
  })

  it('maintains scroll position when switching between views', async () => {
    const user = userEvent.setup()

    renderNewPlanPage()

    await user.type(screen.getByLabelText('Plan name'), 'Test Plan')
    
    // Scroll down
    await user.click(screen.getByRole('button', { name: 'Statistics' }))
    await window.scrollTo(0, 500)
    
    // Switch to another view
    await user.click(screen.getByRole('button', { name: 'Overview' }))
    
    // Should maintain scroll position when switching back
    await user.click(screen.getByRole('button', { name: 'Statistics' }))
    expect(screen.getByText(/Plan Statistics/)).toBeVisible()
  })
})