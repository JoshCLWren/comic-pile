/* eslint-disable */
import { type ComponentProps, type PropsWithChildren } from 'react'
import { render, screen, waitFor, cleanup } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { continuityPlansApi } from '../services/api-continuity-plans'
import { dependencyGroupsApi } from '../services/api-dependency-groups'
import { issuesApi } from '../services/api-issues'
import { threadsApi } from '../services/api-threads'
import { tagsApi } from '../services/api-tags'
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
  getPlanTags: vi.fn(),
}

const _origCreate = continuityPlansApi.create
const _origList = continuityPlansApi.list
const _origGet = continuityPlansApi.get
const _origUpdate = continuityPlansApi.update
const _origGroupsList = dependencyGroupsApi.list
const _origIssuesList = issuesApi.list
const _origThreadsList = threadsApi.list
const _origThreadsGet = threadsApi.get
const _origTagsEffectiveForPlan = tagsApi.effectiveForPlan

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
  if (typeof window !== 'undefined') {
    window.localStorage.clear()
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
  tagsApi.effectiveForPlan = mocks.getPlanTags as never
  vi.clearAllMocks()
  mocks.create.mockReset()
  mocks.get.mockReset()
  mocks.update.mockReset()
  mocks.list.mockResolvedValue({ plans: [], next_page_token: null })
  mocks.listGroups.mockResolvedValue([])
  mocks.listIssues.mockReset()
  mocks.listIssues.mockResolvedValue({ issues: [issue], total_count: 1, page_size: 100, next_page_token: null })
  mocks.getIssue.mockResolvedValue(issue)
  mocks.listThreads.mockResolvedValue({ threads: [thread], next_page_token: null })
  mocks.getThread.mockResolvedValue(thread)
  mocks.getPlanTags.mockResolvedValue({
    target_type: 'ContinuityPlan',
    target_id: 12,
    direct_tags: [],
    effective_tags: [],
  })
  mocks.get.mockResolvedValue({
    id: 12,
    user_id: 1,
    name: 'Saved lane',
    ordering_mode: 'informational',
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
  tagsApi.effectiveForPlan = _origTagsEffectiveForPlan
})

describe('scratch #3607 repro', () => {
  it('EXISTING PLAN editor: issue select enabled after picking a series', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/continuity-plans/12/edit']}>
        <Routes>
          <Route path="/continuity-plans/:id/edit" element={<ContinuityPlannerPage />} />
        </Routes>
      </MemoryRouter>,
      { wrapper: queryWrapper },
    )

    await screen.findByLabelText('Comic series')
    await user.type(screen.getByLabelText('Comic series'), 'Mister')
    await user.click(await screen.findByRole('option', { name: /Mister Miracle/i }))
    await screen.findByRole('option', { name: /Annual 1/i })

    const issueSelect = screen.getByLabelText('Issue') as HTMLSelectElement
    console.log('EXISTING PLAN -> disabled:', issueSelect.disabled, 'options:', issueSelect.options.length)
    console.log('EXISTING PLAN -> option disabled flags:', Array.from(issueSelect.options).map((o) => o.disabled))
    console.log('EXISTING PLAN -> outerHTML:', issueSelect.outerHTML.slice(0, 400))
    expect(issueSelect.disabled).toBe(false)
  })

  it('NEW PLAN editor: issue select enabled after picking a series', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/continuity-plans/new']}>
        <Routes>
          <Route path="/continuity-plans/new" element={<ContinuityPlannerPage />} />
        </Routes>
      </MemoryRouter>,
      { wrapper: queryWrapper },
    )

    await user.type(screen.getByLabelText('Comic series'), 'Mister')
    await user.click(await screen.findByRole('option', { name: /Mister Miracle/i }))
    await screen.findByRole('option', { name: /Annual 1/i })

    const issueSelect = screen.getByLabelText('Issue') as HTMLSelectElement
    console.log('NEW PLAN -> disabled:', issueSelect.disabled, 'options:', issueSelect.options.length)
    expect(issueSelect.disabled).toBe(false)
  })

  it('BEFORE picking a series: what does the issue select look like?', async () => {
    render(
      <MemoryRouter initialEntries={['/continuity-plans/new']}>
        <Routes>
          <Route path="/continuity-plans/new" element={<ContinuityPlannerPage />} />
        </Routes>
      </MemoryRouter>,
      { wrapper: queryWrapper },
    )
    await waitFor(() => expect(screen.getByLabelText('Issue')).toBeInTheDocument())
    const issueSelect = screen.getByLabelText('Issue') as HTMLSelectElement
    console.log('NO SERIES -> disabled:', issueSelect.disabled, 'options:', issueSelect.options.length)
    console.log('NO SERIES -> html:', issueSelect.outerHTML.slice(0, 300))
  })
})
