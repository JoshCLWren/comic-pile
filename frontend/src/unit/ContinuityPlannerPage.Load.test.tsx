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
  mocks.listIssues.mockReset()
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
  it('loads persisted plan contents without a standalone readiness client', async () => {
    mocks.list.mockResolvedValue({
      plans: [plan],
      next_page_token: null,
    })
    mocks.get.mockResolvedValue(plan)

    renderNewPlanPage()

    await screen.findByText('Kirby lane')
    expect(screen.getByText('Kirby lane')).toBeInTheDocument()
  })

  it('reopens the last saved plan when the local-storage marker exists', async () => {
    localStorage.setItem('lastPlanId', '12')

    mocks.list.mockResolvedValue({
      plans: [plan],
      next_page_token: null,
    })
    mocks.get.mockResolvedValue(plan)

    renderNewPlanPage()

    await screen.findByText('Kirby lane')
    expect(screen.getByText('Kirby lane')).toBeInTheDocument()
  })

  it('ignores stale issue requests when the user switches thread selections', async () => {
    const user = userEvent.setup()
    
    renderNewPlanPage()

    await user.click(screen.getByText('Mister Miracle'))
    await user.click(screen.getByText('New Gods'))
    
    // The issue request for Mister Miracle should be cancelled
    // and not affect the New Gods selection
    expect(mocks.listIssues).toHaveBeenCalledTimes(1)
  })

  it('shows an inline error when loading issues for the selected comic fails', async () => {
    mocks.listIssues.mockRejectedValue(new Error('Failed to load issues'))

    renderNewPlanPage()

    await screen.findByText('Mister Miracle')
    await userEvent.click(screen.getByText('Mister Miracle'))
    
    await screen.findByText(/Failed to load issues/)
    expect(screen.getByText(/Failed to load issues/)).toBeInTheDocument()
  })

  it('pages through threads across multiple tokenized responses', async () => {
    const firstPage = {
      threads: [thread],
      next_page_token: 'token1',
      total_count: 2,
      page_size: 100,
    }
    
    const secondPage = {
      threads: [secondThread],
      next_page_token: null,
      total_count: 2,
      page_size: 100,
    }

    mocks.listThreads
      .mockResolvedValueOnce(firstPage)
      .mockResolvedValueOnce(secondPage)

    renderNewPlanPage()

    await screen.findByText('Mister Miracle')
    await userEvent.click(screen.getByText('Load more'))
    
    await screen.findByText('New Gods')
    expect(screen.getByText('New Gods')).toBeInTheDocument()
  })

  it('breaks the pagination loop when the API repeats the same next_page_token', async () => {
    const repeatedResponse = {
      threads: [thread],
      next_page_token: 'same_token',
      total_count: 1,
      page_size: 100,
    }

    mocks.listThreads.mockResolvedValue(repeatedResponse)

    renderNewPlanPage()

    await screen.findByText('Mister Miracle')
    await userEvent.click(screen.getByText('Load more'))
    
    // Should not keep loading indefinitely
    expect(mocks.listThreads).toHaveBeenCalledTimes(2)
  })

  it('ignores plan hydration that resolves after the page has unmounted', async () => {
    const renderResult = renderNewPlanPage()
    
    // Unmount the component
    renderResult.unmount()
    
    // Mock a slow API response
    mocks.get.mockResolvedValue(plan)
    
    // Should not cause any errors or state updates
    await vi.waitFor(() => {
      expect(mocks.get).toHaveBeenCalled()
    })
  })

  it('shows a plan-level load error when fetching the plan fails', async () => {
    mocks.get.mockRejectedValue(new Error('Plan not found'))

    renderNewPlanPage()

    await screen.findByText(/Plan not found/)
    expect(screen.getByText(/Plan not found/)).toBeInTheDocument()
  })
})