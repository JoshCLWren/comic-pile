import { type ComponentProps, type PropsWithChildren } from 'react'
import { render, screen, waitFor, cleanup } from '@testing-library/react'
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

const secondIssue = {
  id: 41,
  thread_id: 5,
  issue_number: '7',
  position: 7,
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
  it('loads persisted plan contents without a standalone readiness client', async () => {
    expect('readiness' in continuityPlansApi).toBe(false)
    mocks.get.mockResolvedValue({
      id: 12,
      user_id: 1,
      name: 'Saved lane',
      ordering_mode: 'strict_sequential',
      lanes: [{ id: 'main', name: 'Reading order', order: 0 }],
      nodes: [
        { id: 'issue-40', node_type: 'issue', ref_id: 40, lane_id: 'main', position: 0, label: 'Mister Miracle #Annual 1' },
        { id: 'crossover-8', node_type: 'crossover', ref_id: 8, lane_id: 'main', position: 1, label: 'Fourth World' },
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
      { wrapper: queryWrapper },
    )

    expect(await screen.findByText('Mister Miracle #Annual 1')).toBeVisible()
    expect(screen.getByRole('button', { name: 'Remove Fourth World' })).toBeVisible()
    expect(screen.getByDisplayValue('Saved lane')).toBeVisible()
    await waitFor(() => expect(mocks.get).toHaveBeenCalledWith(12))
    expect(mocks.get).toHaveBeenCalledTimes(1)
  })

  it('reopens the last saved plan when the local-storage marker exists', async () => {
    window.localStorage.setItem('comic-pile:last-continuity-plan', '12')
    mocks.get.mockResolvedValue({
      id: 12,
      user_id: 1,
      name: 'Saved lane',
      ordering_mode: 'strict_sequential',
      lanes: [{ id: 'main', name: 'Reading order', order: 0 }],
      nodes: [],
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

    const reopen = await screen.findByRole('button', { name: 'Reopen last saved plan' })
    await user.click(reopen)
    await waitFor(() => expect(mocks.get).toHaveBeenCalledWith(12))
  })

  it('ignores stale issue requests when the user switches thread selections', async () => {
    let resolveFirst!: (value: { issues: typeof issue[]; total_count: number; page_size: number; next_page_token: null }) => void
    const firstList = new Promise<{ issues: typeof issue[]; total_count: number; page_size: number; next_page_token: null }>((resolve) => {
      resolveFirst = resolve
    })
    mocks.listIssues
      .mockImplementationOnce(() => firstList)
      .mockResolvedValueOnce({ issues: [secondIssue], total_count: 1, page_size: 100, next_page_token: null })

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
    await user.clear(screen.getByLabelText('Comic series'))
    await user.type(screen.getByLabelText('Comic series'), 'New');
    await user.click(screen.getByRole('option', { name: /New Gods/i }))
    await screen.findByRole('option', { name: /#7$/ })
    resolveFirst({ issues: [issue], total_count: 1, page_size: 100, next_page_token: null })
    await waitFor(() => expect(screen.queryByRole('option', { name: /#Annual 1$/ })).not.toBeInTheDocument())
  })

  it('shows an inline error when loading issues for the selected comic fails', async () => {
    mocks.listIssues.mockReset()
    mocks.listIssues.mockRejectedValueOnce(new Error('network down'))

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
    expect(await screen.findByRole('alert')).toHaveTextContent(/network down/i)
  })

  it('shows a plan-level load error when fetching the plan fails', async () => {
    mocks.get.mockRejectedValueOnce(new Error('Cannot read plan'))

    render(
      <MemoryRouter initialEntries={['/continuity-plans/12']}>
        <Routes>
          <Route path="/continuity-plans/:id" element={<ContinuityPlannerPage />} />
        </Routes>
      </MemoryRouter>,
      { wrapper: queryWrapper },
    )

    expect(await screen.findByRole('alert')).toHaveTextContent(/Cannot read plan/i)
  })

  it('pages through threads across multiple tokenized responses', async () => {
    mocks.listThreads.mockReset()
    mocks.listThreads
      .mockResolvedValueOnce({ threads: [thread], next_page_token: 'page-2' })
      .mockResolvedValueOnce({ threads: [secondThread], next_page_token: null })
    mocks.listIssues.mockReset()
    mocks.listIssues
      .mockResolvedValueOnce({ issues: [issue], total_count: 1, page_size: 100, next_page_token: 'issues-2' })
      .mockResolvedValueOnce({ issues: [secondIssue], total_count: 1, page_size: 100, next_page_token: null })

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

    await waitFor(() => expect(mocks.listThreads).toHaveBeenCalledTimes(2))
    await user.type(screen.getByLabelText('Comic series'), 'New');
    expect(await screen.findByRole('option', { name: /New Gods/i })).toBeVisible()
    await user.click(screen.getByRole('option', { name: /New Gods/i }))
    await screen.findByRole('option', { name: /#7$/ })
  })

  it('breaks the pagination loop when the API repeats the same next_page_token', async () => {
    mocks.listThreads.mockReset()
    mocks.listThreads
      .mockResolvedValueOnce({ threads: [thread], next_page_token: 'duplicate' })
      .mockResolvedValueOnce({ threads: [secondThread], next_page_token: 'duplicate' })

    render(
      <MemoryRouter initialEntries={['/continuity-plans']}>
        <Routes>
          <Route path="/continuity-plans" element={<ContinuityPlannerPage />} />
          <Route path="/continuity-plans/:id" element={<ContinuityPlannerPage />} />
        </Routes>
      </MemoryRouter>,
      { wrapper: queryWrapper },
    )

    await waitFor(() => expect(mocks.listThreads).toHaveBeenCalledTimes(2))
  })

  it('breaks the issue pagination loop when the API repeats the same next_page_token', async () => {
    mocks.listIssues.mockReset()
    mocks.listIssues
      .mockResolvedValueOnce({ issues: [issue], total_count: 1, page_size: 100, next_page_token: 'repeat' })
      .mockResolvedValueOnce({ issues: [secondIssue], total_count: 1, page_size: 100, next_page_token: 'repeat' })

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
    await waitFor(() => expect(mocks.listIssues).toHaveBeenCalledTimes(2))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('does not surface an error from an issue request that was aborted by a thread switch', async () => {
    mocks.listIssues.mockReset()
    mocks.listIssues
      .mockImplementationOnce(() => Promise.reject(new Error('stale failure')))
      .mockResolvedValueOnce({ issues: [secondIssue], total_count: 1, page_size: 100, next_page_token: null })

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
    await user.clear(screen.getByLabelText('Comic series'))
    await user.type(screen.getByLabelText('Comic series'), 'New');
    await user.click(screen.getByRole('option', { name: /New Gods/i }))
    await screen.findByRole('option', { name: /#7$/ })
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())
  })

  it('ignores plan hydration that resolves after the page has unmounted', async () => {
    let resolveThreads!: (value: { threads: typeof thread[]; next_page_token: string | null }) => void
    mocks.listThreads.mockReset()
    mocks.listThreads.mockImplementationOnce(() => new Promise((resolve) => {
      resolveThreads = resolve
    }))

    const { unmount } = render(
      <MemoryRouter initialEntries={['/continuity-plans']}>
        <Routes>
          <Route path="/continuity-plans" element={<ContinuityPlannerPage />} />
          <Route path="/continuity-plans/:id" element={<ContinuityPlannerPage />} />
        </Routes>
      </MemoryRouter>,
      { wrapper: queryWrapper },
    )

    unmount()
    resolveThreads({ threads: [thread], next_page_token: null })
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(mocks.get).not.toHaveBeenCalled()
  })

})
