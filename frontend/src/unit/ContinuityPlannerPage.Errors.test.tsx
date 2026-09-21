import { type ComponentProps, type PropsWithChildren } from 'react'
import { render, screen, cleanup } from '@testing-library/react'
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
  it('surfaces a save error without discarding the in-progress plan', async () => {
    mocks.create.mockReset()
    mocks.create.mockRejectedValueOnce({
      isAxiosError: true,
      response: { data: { detail: { code: 'plan_rule_conflict' } } },
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

    await user.clear(await screen.findByLabelText('Plan name'))
    await user.type(screen.getByLabelText('Plan name'), 'Kirby lane')
    await user.type(screen.getByLabelText('Comic series'), 'Mister');
    await user.click(screen.getByRole('option', { name: /Mister Miracle/i }))
    await screen.findByRole('option', { name: /Annual 1/i })
    await user.selectOptions(screen.getByLabelText('Issue'), '40')
    await user.click(screen.getByRole('button', { name: 'Add issue' }))
    await user.click(screen.getByRole('button', { name: 'Save plan' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/conflicts with an existing continuity rule/i)
  })

  it('surfaces a cycle error when the API rejects with the continuity_cycle code', async () => {
    mocks.create.mockReset()
    mocks.create.mockRejectedValueOnce({
      isAxiosError: true,
      response: { data: { detail: { code: 'continuity_cycle' } } },
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
    await user.click(screen.getByRole('button', { name: 'Save plan' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/continuity cycle/i)
  })

  it('surfaces a specific conflict message when source and target nodes are identified in the plan', async () => {
    mocks.create.mockReset()
    mocks.create.mockRejectedValueOnce({
      isAxiosError: true,
      response: {
        data: {
          detail: {
            code: 'plan_rule_conflict',
            source_node_id: 'issue-40',
            target_node_id: 'crossover-8',
          },
        },
      },
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

    await user.clear(await screen.findByLabelText('Plan name'))
    await user.type(screen.getByLabelText('Plan name'), 'Kirby lane')
    await user.type(screen.getByLabelText('Comic series'), 'Mister');
    await user.click(screen.getByRole('option', { name: /Mister Miracle/i }))
    await screen.findByRole('option', { name: /Annual 1/i })
    await user.selectOptions(screen.getByLabelText('Issue'), '40')
    await user.click(screen.getByRole('button', { name: 'Add issue' }))
    await user.selectOptions(screen.getByLabelText('Crossover'), '8')
    await user.click(screen.getByRole('button', { name: 'Add crossover' }))
    await user.click(screen.getByRole('button', { name: 'Save plan' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/You already require "Mister Miracle #Annual 1" before "Fourth World"/i)
  })

  it('surfaces a specific cycle message when source and target nodes are identified in the plan', async () => {
    mocks.create.mockReset()
    mocks.create.mockRejectedValueOnce({
      isAxiosError: true,
      response: {
        data: {
          detail: {
            code: 'continuity_cycle',
            source_node_id: 'issue-40',
            target_node_id: 'crossover-8',
          },
        },
      },
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
    await user.click(screen.getByRole('button', { name: 'Save plan' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/This order would create a continuity cycle: "Mister Miracle #Annual 1" → "Fourth World"/i)
  })

  it('falls back to generic conflict message when source and target node IDs are provided but not found in the plan', async () => {
    mocks.create.mockReset()
    mocks.create.mockRejectedValueOnce({
      isAxiosError: true,
      response: {
        data: {
          detail: {
            code: 'plan_rule_conflict',
            source_node_id: 'missing-1',
            target_node_id: 'missing-2',
          },
        },
      },
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

    await user.clear(await screen.findByLabelText('Plan name'))
    await user.type(screen.getByLabelText('Plan name'), 'Kirby lane')
    await user.type(screen.getByLabelText('Comic series'), 'Mister');
    await user.click(screen.getByRole('option', { name: /Mister Miracle/i }))
    await screen.findByRole('option', { name: /Annual 1/i })
    await user.selectOptions(screen.getByLabelText('Issue'), '40')
    await user.click(screen.getByRole('button', { name: 'Add issue' }))
    await user.click(screen.getByRole('button', { name: 'Save plan' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/This order conflicts with an existing continuity rule. Change the sequence and try again./i)
  })

  it('falls back to generic cycle message when source and target node IDs are provided but not found in the plan', async () => {
    mocks.create.mockReset()
    mocks.create.mockRejectedValueOnce({
      isAxiosError: true,
      response: {
        data: {
          detail: {
            code: 'continuity_cycle',
            source_node_id: 'missing-1',
            target_node_id: 'missing-2',
          },
        },
      },
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
    await user.click(screen.getByRole('button', { name: 'Save plan' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/This order would create a continuity cycle. Change the sequence and try again./i)
  })

  it('surfaces a conflict error on update when the API rejects with plan_rule_conflict', async () => {
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
    mocks.update.mockReset()
    mocks.update.mockRejectedValueOnce({
      isAxiosError: true,
      response: { data: { detail: { code: 'plan_rule_conflict' } } },
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

    // Make a change to dirty the plan
    const moveDown = await screen.findByRole('button', { name: /Move Mister Miracle #Annual 1 later/i })
    await user.click(moveDown)
    await user.click(screen.getByRole('button', { name: 'Save plan' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/conflicts with an existing continuity rule/i)
  })

  it('surfaces a cycle error on update when the API rejects with continuity_cycle', async () => {
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
    mocks.update.mockReset()
    mocks.update.mockRejectedValueOnce({
      isAxiosError: true,
      response: { data: { detail: { code: 'continuity_cycle' } } },
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

    // Make a change to dirty the plan
    const moveDown = await screen.findByRole('button', { name: /Move Mister Miracle #Annual 1 later/i })
    await user.click(moveDown)
    await user.click(screen.getByRole('button', { name: 'Save plan' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/continuity cycle/i)
  })

  it('shows an error for a non-numeric route id', async () => {
    render(
      <MemoryRouter initialEntries={['/continuity-plans/not-a-number']}>
        <Routes>
          <Route path="/continuity-plans" element={<ContinuityPlannerPage />} />
          <Route path="/continuity-plans/:id" element={<ContinuityPlannerPage />} />
        </Routes>
      </MemoryRouter>,
      { wrapper: queryWrapper },
    )

    expect(await screen.findByRole('alert')).toHaveTextContent(/Invalid continuity plan ID/i)
    expect(mocks.get).not.toHaveBeenCalled()
  })

  it('shows an error for a zero route id', async () => {
    render(
      <MemoryRouter initialEntries={['/continuity-plans/0']}>
        <Routes>
          <Route path="/continuity-plans" element={<ContinuityPlannerPage />} />
          <Route path="/continuity-plans/:id" element={<ContinuityPlannerPage />} />
        </Routes>
      </MemoryRouter>,
      { wrapper: queryWrapper },
    )

    expect(await screen.findByRole('alert')).toHaveTextContent(/Invalid continuity plan ID/i)
    expect(mocks.get).not.toHaveBeenCalled()
  })

  it('shows an error for a negative route id', async () => {
    render(
      <MemoryRouter initialEntries={['/continuity-plans/-1']}>
        <Routes>
          <Route path="/continuity-plans" element={<ContinuityPlannerPage />} />
          <Route path="/continuity-plans/:id" element={<ContinuityPlannerPage />} />
        </Routes>
      </MemoryRouter>,
      { wrapper: queryWrapper },
    )

    expect(await screen.findByRole('alert')).toHaveTextContent(/Invalid continuity plan ID/i)
    expect(mocks.get).not.toHaveBeenCalled()
  })

  it('rejects adding the same issue or crossover twice and surfaces an inline error', async () => {
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
    await user.selectOptions(screen.getByLabelText('Issue'), '40')
    await user.click(screen.getByRole('button', { name: 'Add issue' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/already in this plan/i)

    await user.selectOptions(screen.getByLabelText('Crossover'), '8')
    await user.click(screen.getByRole('button', { name: 'Add crossover' }))
    await user.selectOptions(screen.getByLabelText('Crossover'), '8')
    await user.click(screen.getByRole('button', { name: 'Add crossover' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/already in this plan/i)
  })

  it('requires a non-empty plan name before save', async () => {
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
    await user.type(nameInput, '   ')
    await user.type(screen.getByLabelText('Comic series'), 'Mister');
    await user.click(await screen.findByRole('option', { name: /Mister Miracle/i }))
    await screen.findByRole('option', { name: /Annual 1/i })
    await user.selectOptions(screen.getByLabelText('Issue'), '40')
    await user.click(screen.getByRole('button', { name: 'Add issue' }))
    await user.click(screen.getByRole('button', { name: 'Save plan' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/Enter a plan name\./i)
    expect(mocks.create).not.toHaveBeenCalled()
  })

  it('falls back to the thrown error message when the save error has no axios detail', async () => {
    mocks.create.mockReset()
    mocks.create.mockRejectedValueOnce(new Error('Boom'))

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
    await user.click(screen.getByRole('button', { name: 'Save plan' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/Boom/i)
  })

  it('falls back to the generic save message when the rejection is neither an axios detail nor an Error', async () => {
    mocks.create.mockReset()
    mocks.create.mockRejectedValueOnce({ code: 500 })

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
    await user.click(screen.getByRole('button', { name: 'Save plan' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/Unable to save this continuity plan\./i)
  })

  it('uses the API detail string when the save error payload includes one', async () => {
    mocks.create.mockReset()
    mocks.create.mockRejectedValueOnce({
      isAxiosError: true,
      response: { data: { detail: 'Backend rejected the plan.' } },
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
    await user.click(screen.getByRole('button', { name: 'Save plan' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/Backend rejected the plan\./i)
  })

  it('falls back to the generic save message when the API detail is an object without a code', async () => {
    mocks.create.mockReset()
    mocks.create.mockRejectedValueOnce({
      isAxiosError: true,
      response: { data: { detail: { message: 'no code here' } } },
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
    await user.click(screen.getByRole('button', { name: 'Save plan' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/Unable to save this continuity plan\./i)
  })

  it('falls back to the generic save message when the API detail has an unrecognized code', async () => {
    mocks.create.mockReset()
    mocks.create.mockRejectedValueOnce({
      isAxiosError: true,
      response: { data: { detail: { code: 'some_other_error' } } },
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
    await user.click(screen.getByRole('button', { name: 'Save plan' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/Unable to save this continuity plan\./i)
  })

  it('falls back to the generic save message when the API detail is an object without a known code', async () => {
    mocks.create.mockReset()
    mocks.create.mockRejectedValueOnce({
      isAxiosError: true,
      response: { data: { detail: { problem: 'wrapped failure' } } },
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
    await user.click(screen.getByRole('button', { name: 'Save plan' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/Unable to save this continuity plan\./i)
  })

})
